#!/usr/bin/env python3
"""
Migrate all documents from Firebase Cloud Storage to Cloudflare R2.
Reads Firebase access token from ~/.config/configstore/firebase-tools.json
and Cloudflare R2 credentials from .env.
"""

import os
import sys
import json
import urllib.parse
import urllib.request
import datetime
import hashlib
import hmac
from pathlib import Path

def load_env(env_path):
    env = {}
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env

def get_firebase_token():
    config_path = Path.home() / '.config' / 'configstore' / 'firebase-tools.json'
    if not config_path.exists():
        print(f"Error: Firebase config not found at {config_path}")
        sys.exit(1)
    with open(config_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    token = data.get('tokens', {}).get('access_token')
    if not token:
        print("Error: No access_token found in firebase-tools.json")
        sys.exit(1)
    return token

def sign(key, msg):
    return hmac.new(key, msg.encode('utf-8'), hashlib.sha256).digest()

def get_signature_key(key, date_stamp, region_name, service_name):
    k_date = sign(('AWS4' + key).encode('utf-8'), date_stamp)
    k_region = sign(k_date, region_name)
    k_service = sign(k_region, service_name)
    k_signing = sign(k_service, 'aws4_request')
    return k_signing

def upload_to_r2(s3_key, data, content_type, env):
    access_key = env['R2_ACCESS_KEY_ID']
    secret_key = env['R2_SECRET_ACCESS_KEY']
    account_id = env['CLOUDFLARE_ACCOUNT_ID']
    bucket = env['R2_BUCKET_NAME']
    endpoint_host = f"{account_id}.r2.cloudflarestorage.com"
    region = 'auto'
    service = 's3'

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
        return resp.status in (200, 204)

def main():
    base_dir = Path(__file__).resolve().parent.parent
    env = load_env(base_dir / '.env')
    fb_token = get_firebase_token()
    bucket_name = 'sugandha-enterprises.appspot.com'

    print(f"Listing all objects from Firebase Storage bucket: {bucket_name} ...")
    items = []
    page_token = None

    while True:
        url = f"https://storage.googleapis.com/storage/v1/b/{bucket_name}/o?maxResults=1000"
        if page_token:
            url += f"&pageToken={urllib.parse.quote(page_token)}"
        req = urllib.request.Request(url, headers={'Authorization': f"Bearer {fb_token}"})
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                items.extend(data.get('items', []))
                page_token = data.get('nextPageToken')
                if not page_token:
                    break
        except Exception as e:
            print(f"Failed to list objects: {e}")
            sys.exit(1)

    # Filter out directory placeholder objects (0 bytes or ending in /)
    file_items = [it for it in items if int(it.get('size', 0)) > 0 and not it['name'].endswith('/')]
    print(f"Found {len(file_items)} files to migrate ({len(items)} total objects including folders).")

    success_count = 0
    fail_count = 0

    for idx, item in enumerate(file_items, 1):
        name = item['name']
        size = int(item['size'])
        content_type = item.get('contentType', 'application/pdf')

        encoded_name = urllib.parse.quote(name, safe='')
        download_url = f"https://storage.googleapis.com/storage/v1/b/{bucket_name}/o/{encoded_name}?alt=media"

        dl_req = urllib.request.Request(download_url, headers={'Authorization': f"Bearer {fb_token}"})
        try:
            with urllib.request.urlopen(dl_req) as dl_resp:
                content = dl_resp.read()
            
            ok = upload_to_r2(name, content, content_type, env)
            if ok:
                print(f"[{idx}/{len(file_items)}] ✓ {name} ({size:,} bytes)")
                success_count += 1
            else:
                print(f"[{idx}/{len(file_items)}] ✗ Failed uploading {name}")
                fail_count += 1
        except Exception as e:
            print(f"[{idx}/{len(file_items)}] ✗ Error with {name}: {e}")
            fail_count += 1

    print("\n" + "=" * 50)
    print(f"Migration completed! {success_count} succeeded, {fail_count} failed.")
    print(f"All files accessible via: {env.get('R2_PUBLIC_DOMAIN', 'https://docs.sugandhaenterprises.com')}/<path>")

if __name__ == '__main__':
    main()
