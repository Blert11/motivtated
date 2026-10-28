import hashlib
import json
import os
import re
import subprocess
import zipfile
from pathlib import Path

from .common import HTTP, clip_id, env, json_bytes, require, sha256, Stop

MAX_VIDEO = 200 * 1024 * 1024


def validate_caption(raw):
    text = raw.decode('utf-8-sig').strip()
    require(len(text.splitlines()) == 1 and 1 <= len(text) <= 2200, 'Caption must be one nonempty line, at most 2200 characters.')
    require(re.findall(r'#\w+', text) == ['#motivtated'], 'Caption must have exactly one hashtag: #motivtated.')
    require(text.endswith(('👑', '🥇', '🏆')), 'Caption must end with a motivational emoji.')
    require(sum(text.count(e) for e in ['👑', '🥇', '🏆']) == 1, 'Use one motivational emoji, at the end.')
    return text


def probe(video):
    try:
        p = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(video)],
                           capture_output=True, text=True, encoding='utf-8', timeout=60, check=True)
        result = json.loads(p.stdout)
        v = next(s for s in result['streams'] if s['codec_type'] == 'video')
        a = next(s for s in result['streams'] if s['codec_type'] == 'audio')
        duration = float(result['format']['duration'])
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, StopIteration):
        raise Stop('ffprobe failed or media lacks video/audio. Install ffmpeg and inspect the clip.') from None
    require(v['codec_name'] == 'h264' and a['codec_name'] == 'aac', 'Posting requires H.264 video and AAC audio.')
    require((v['width'], v['height']) == (1080, 1920), 'Expected a 1080x1920 portrait export.')
    require(3 <= duration <= 76, 'Expected clip duration between 3 and approximately 75 seconds.')
    return {'duration_seconds': duration, 'video': 'h264', 'audio': 'aac', 'width': 1080, 'height': 1920}


def prepare(root, identifier, output):
    """Make a private upload bundle; leave Staging, Ready, Posted and the allocator alone."""
    identifier = clip_id(identifier)
    require(not output.exists(), 'Bundle already exists; choose a new output path.')
    stage = root / 'Staging'
    paths = {'video.mp4': stage/'Clips'/f'{identifier}.mp4',
             'caption.txt': stage/'Captions'/f'{identifier}.txt',
             'metadata.json': stage/'Metadata'/f'{identifier}.json'}
    require(all(p.is_file() for p in paths.values()), 'Video, caption, and metadata must all exist.')
    require(paths['video.mp4'].stat().st_size <= MAX_VIDEO, 'Video exceeds the milestone size limit.')
    caption = validate_caption(paths['caption.txt'].read_bytes())
    meta = json.loads(paths['metadata.json'].read_text(encoding='utf-8-sig'))
    registry = json.loads((root/'Control'/'registry.json').read_text(encoding='utf-8'))
    record = registry['clips'].get(identifier, {})
    require(record.get('state') == 'staged', 'Clip must be validated and staged in the registry.')
    hashes = {name: sha256(path) for name, path in paths.items()}
    require(meta.get('sha256') == hashes['video.mp4'] == record.get('sha256'), 'Video source hash mismatch.')
    for name, field in [('caption.txt','caption_sha256'), ('metadata.json','metadata_sha256')]:
        require(hashes[name] == record.get(field), f'{name} lacks validation or changed after validation; revalidate first.')
    source_hash = record.get('source_sha256')
    require(bool(re.fullmatch(r'[0-9a-f]{64}', source_hash or '')), 'Missing original source SHA256; validate the source first.')
    source = Path(record.get('source_video') or '')
    require(source.is_file() and sha256(source) == source_hash, 'Original source file is missing or changed.')
    manifest = {'version': 1, 'clip_id': identifier, 'source_sha256': source_hash,
                'files': {name: {'sha256': hashes[name], 'size': path.stat().st_size} for name,path in paths.items()},
                'probe': probe(paths['video.mp4']), 'caption': caption}
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_STORED) as z:
        for name, path in paths.items():
            z.write(path, name)
        z.writestr('manifest.json', json_bytes(manifest))
    with zipfile.ZipFile(output) as z:
        for name in paths:
            with z.open(name) as f:
                require(hashlib.file_digest(f, 'sha256').hexdigest() == hashes[name], 'Input changed during bundle preparation; discard this bundle.')
    return {'clip_id': identifier, 'bundle_sha256': sha256(output), 'bundle_file': str(output)}


def unpack(bundle, expected_hash, directory):
    require(bool(re.fullmatch(r'[0-9a-f]{64}', expected_hash)), 'A bundle SHA256 is required.')
    require(sha256(bundle) == expected_hash, 'Bundle SHA256 does not match the approved input.')
    with zipfile.ZipFile(bundle) as z:
        names = ['video.mp4','caption.txt','metadata.json','manifest.json']
        require(len(z.namelist()) == 4 and set(z.namelist()) == set(names), 'Unexpected or duplicate files in bundle.')
        for info in z.infolist():
            limit = MAX_VIDEO if info.filename == 'video.mp4' else 1024 * 1024
            require(info.file_size <= limit, 'Bundle member is too large.')
            with z.open(info) as source, (directory/info.filename).open('xb') as target:
                size = 0
                while chunk := source.read(1024 * 1024):
                    size += len(chunk)
                    require(size <= limit, 'Expanded bundle member exceeds size limit.')
                    target.write(chunk)
    manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    require(manifest.get('version') == 1, 'Unsupported bundle version.')
    clip_id(manifest['clip_id'])
    require(set(manifest['files']) == {'video.mp4','caption.txt','metadata.json'}, 'Incomplete bundle manifest.')
    for name, expected in manifest['files'].items():
        p = directory/name
        require(p.stat().st_size == expected['size'] and sha256(p) == expected['sha256'], f'{name} hash/size mismatch.')
    require(re.fullmatch(r'[0-9a-f]{64}', manifest.get('source_sha256', '')), 'Missing source hash.')
    caption = validate_caption((directory/'caption.txt').read_bytes())
    require(caption == manifest['caption'], 'Caption differs from manifest.')
    meta = json.loads((directory/'metadata.json').read_text(encoding='utf-8-sig'))
    require(meta.get('sha256') == manifest['files']['video.mp4']['sha256'], 'Metadata video hash mismatch.')
    require(meta.get('id', manifest['clip_id']) == manifest['clip_id'], 'Metadata clip ID mismatch.')
    probe(directory/'video.mp4')
    return manifest


def download_drive(file_id, destination, expected_hash, http=None):
    require(re.fullmatch(r'[A-Za-z0-9_-]{10,200}', file_id), 'Invalid Google Drive file ID.')
    http = http or HTTP()
    token = http.json('POST', 'https://oauth2.googleapis.com/token', form={
        'client_id': env('GOOGLE_CLIENT_ID'), 'client_secret': env('GOOGLE_CLIENT_SECRET'),
        'refresh_token': env('GOOGLE_REFRESH_TOKEN'), 'grant_type': 'refresh_token'})
    require(token.get('access_token'), 'Google did not return an access token.')
    headers = {'Authorization': f"Bearer {token['access_token']}"}
    meta = http.json('GET', f'https://www.googleapis.com/drive/v3/files/{file_id}?fields=size,mimeType,trashed&supportsAllDrives=true', headers)
    require(not meta.get('trashed') and 0 < int(meta.get('size', 0)) <= MAX_VIDEO + 4*1024*1024,
            'Drive bundle is missing, trashed, or too large.')
    http.download(f'https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&supportsAllDrives=true', destination,
                  MAX_VIDEO + 4*1024*1024, headers, expected_hash)


def download_github_release(identifier, destination, expected_hash, gh=None):
    """Download an exact private package without exposing tokens to redirect hosts."""
    from .github import GitHub
    identifier = clip_id(identifier)
    gh = gh or GitHub(env('GITHUB_REPOSITORY'), env('GITHUB_TOKEN'))
    require(gh.request('GET').get('private') is True, 'Bundle repository must be private.')
    release = gh.request('GET', '/releases/tags/posting-inputs')
    matches = [a for a in release.get('assets', []) if a.get('name') == identifier+'.zip']
    require(len(matches) == 1, 'Expected exactly one private release bundle for this clip.')
    asset = matches[0]
    require(asset.get('state') == 'uploaded' and 0 < asset.get('size', 0) <= MAX_VIDEO + 4*1024*1024,
            'Private release bundle is incomplete or too large.')
    if asset.get('digest'):
        require(asset['digest'] == 'sha256:'+expected_hash, 'Release bundle digest differs from the approved package.')
    try:
        result = subprocess.run(['gh', 'release', 'download', 'posting-inputs', '--repo', gh.repo,
            '--pattern', identifier+'.zip', '--output', str(destination)],
            env={**os.environ, 'GH_TOKEN': env('GITHUB_TOKEN'), 'GH_PROMPT_DISABLED': '1'},
            capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        raise Stop('Private GitHub package download failed; no post was created.') from None
    require(result.returncode == 0 and destination.is_file(), 'Private GitHub package download failed; no post was created.')
    require(destination.stat().st_size == asset['size'] and sha256(destination) == expected_hash,
            'Downloaded release package hash/size mismatch; do not publish.')
