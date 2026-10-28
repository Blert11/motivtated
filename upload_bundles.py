"""Agent-owned private package transfer. Does not publish or schedule anything."""
import argparse
import json
import subprocess
from pathlib import Path

from publisher.common import clip_id, require, sha256


def gh(*args):
    result = subprocess.run(['gh', *args], capture_output=True, text=True, encoding='utf-8', timeout=600)
    require(result.returncode == 0, 'GitHub transfer failed; inspect release assets before retrying. No posts were created.')
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--ids', nargs='+', required=True)
    args = parser.parse_args()
    repo = 'Blert11/motivtated'
    require(json.loads(gh('api','repos/'+repo))['private'] is True, 'Repository must be private.')
    release = json.loads(gh('api',f'repos/{repo}/releases/tags/posting-inputs'))
    assets = {a['name']:a for a in release['assets']}
    for identifier in args.ids:
        identifier = clip_id(identifier)
        path = args.directory/(identifier+'.zip')
        receipt = json.loads(path.with_suffix('.receipt.json').read_text(encoding='utf-8'))
        digest = sha256(path)
        require(receipt['clip_id'] == identifier and receipt['bundle_sha256'] == digest, 'Package receipt mismatch.')
        if path.name not in assets:
            gh('release','upload','posting-inputs',str(path),'--repo',repo)
            refreshed = json.loads(gh('api',f'repos/{repo}/releases/tags/posting-inputs'))
            assets = {a['name']:a for a in refreshed['assets']}
        asset = assets.get(path.name,{})
        require(asset.get('state') == 'uploaded' and asset.get('size') == path.stat().st_size
                and asset.get('digest') == 'sha256:'+digest,
                'Uploaded package verification failed; never overwrite or publish automatically.')
        print(json.dumps({'clip_id':identifier,'source':'github-release','bundle_sha256':digest,
                          'asset_id':asset['id'],'status':'uploaded_and_verified'}),flush=True)


if __name__ == '__main__':
    main()
