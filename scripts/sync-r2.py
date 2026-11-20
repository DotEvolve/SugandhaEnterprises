#!/usr/bin/env python3
"""
Sync static profile and statutory documents to Cloudflare R2 bucket.
Uses AWS SigV4 via Python standard library (no external dependencies required).
"""

import os
import sys
import glob
import mimetypes
import datetime
import hashlib
import hmac
import urllib.request
from pathlib import Path

def load_env(env_path):
    env = {}
    if not os.path.exists(env_path):
        print(f"Error: {env_path} does not exist.")
        sys.exit(1)
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env

def sign(key, msg):
    return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()

def get_signature_key(key, date_stamp, region_name, service_name):
    k_date = sign(('AWS4' + key).encode('utf-8'), date_stamp)
    k_region = sign(k_date, region_name)
    k_service = sign(k_region, service_name)
    k_signing = sign(k_service, 'aws4_request')
    return k_signing

def upload_file(local_path, s3_key, env):
    access_key = env['R2_ACCESS_KEY_ID']
    secret_key = env['R2_SECRET_ACCESS_KEY']
    account_id = env['CLOUDFLARE_ACCOUNT_ID']
    bucket = env['R2_BUCKET_NAME']
    endpoint_host = f"{account_id}.r2.cloudflarestorage.com"
    region = 'auto'
    service = 's3'

    content_type, _ = mimetypes.guess_type(local_path)
    if not content_type:
        content_type = 'application/octet-stream'

    with open(local_path, 'rb') as f:
        data = f.read()

    now = datetime.datetime.utcnow()
    amz_date = now.strftime('%Y%m%dT%H%M%SZ')
    date_stamp = now.strftime('%Y%m%d')

    canonical_uri = f"/{bucket}/{s3_key}"
    canonical_querystring = ''
    payload_hash = hashlib.sha256(data).hexdigest()

    headers_to_sign = {
        'content-type': content_type,
        'host': endpoint_host,
        'x-amz-content-sha256': payload_hash,
        'x-amz-date': amz_date
    }
    sorted_keys = sorted(headers_to_sign.keys())
    canonical_headers = ''.join(f"{k}:{headers_to_sign[k]}\n" for k in sorted_keys)
    signed_headers = ';'.join(sorted_keys)

    canonical_request = f"PUT\n{canonical_uri}\n{canonical_querystring}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"

    algorithm = 'AWS4-HMAC-SHA256'
    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = f"{algorithm}\n{amz_date}\n{credential_scope}\n" + hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()

    signing_key = get_signature_key(secret_key, date_stamp, region, service)
    signature = hmac.new(signing_key, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()

    auth_header = f"{algorithm} Credential={access_key}/{credential_scope}, SignedHeaders={signed_headers}, Signature={signature}"

    req = urllib.request.Request(
        f"https://{endpoint_host}{canonical_uri}",
        data=data,
        method='PUT',
        headers={
            'Content-Type': content_type,
            'x-amz-date': amz_date,
            'x-amz-content-sha256': payload_hash,
            'Authorization': auth_header
        }
    )

    with urllib.request.urlopen(req) as resp:
        if resp.status in (200, 204):
            print(f"  ✓ {s3_key} ({len(data):,} bytes)")
        else:
            print(f"  ✗ {s3_key}: HTTP {resp.status}")

def main():
    base_dir = Path(__file__).resolve().parent.parent
    env = load_env(base_dir / '.env')
    public_dir = base_dir / 'public'

    target_dirs = ['profile', 'statutory']
    print(f"Syncing documents to Cloudflare R2 bucket: {env['R2_BUCKET_NAME']}")

    total_files = 0
    for target in target_dirs:
        dir_path = public_dir / target
        if not dir_path.exists():
            continue
        for root, _, files in os.walk(dir_path):
            for file in files:
                if file.startswith('.') or file.endswith('.old.pdf'):
                    continue
                file_path = Path(root) / file
                s3_key = str(file_path.relative_to(public_dir)).replace(os.sep, '/')
                upload_file(str(file_path), s3_key, env)
                total_files += 1

    print(f"\nSuccessfully synced {total_files} documents to R2!")
    print(f"Public Base URL: {env.get('R2_PUBLIC_DOMAIN', 'https://docs.sugandhaenterprises.com')}")

if __name__ == '__main__':
    main()
