import argparse
import json
import os
import tempfile
from pathlib import Path

from .buffer import Buffer
from .bundles import download_drive, prepare, unpack
from .common import Stop, clip_id, env, require
from .engine import Engine
from .github import GitHubLedger
from .media import host_from_env

ACTIONS = ['init-state','discover','validate','publish','reconcile','confirm-public','cleanup','status']


def workflow_arguments():
    return argparse.Namespace(
        command='run', action=env('INPUT_ACTION'),
        clip_id=os.environ.get('INPUT_CLIP_ID','').strip(),
        platform=os.environ.get('INPUT_PLATFORM','').strip(),
        bundle_file_id=os.environ.get('INPUT_BUNDLE_FILE_ID','').strip(),
        bundle_sha256=os.environ.get('INPUT_BUNDLE_SHA256','').strip(),
        post_id=os.environ.get('INPUT_POST_ID','').strip() or None,
        public_url=os.environ.get('INPUT_PUBLIC_URL','').strip(),
        resume=os.environ.get('INPUT_RESUME','false').lower() == 'true',
        confirm_unposted=os.environ.get('INPUT_CONFIRM_UNPOSTED','false').lower() == 'true',
        bundle=None)


def execute(args):
    if args.command == 'prepare':
        return prepare(args.root, args.clip_id, args.output)
    if args.command == 'workflow':
        args = workflow_arguments()
    require(args.action in ACTIONS, 'Unknown action.')
    if args.action in ['publish','validate']:
        require(args.bundle_sha256, 'Provide the approved bundle SHA256.')
        clip_id(args.clip_id)
    if args.action in ['publish','reconcile','confirm-public']:
        require(args.platform in ['tiktok','instagram'], 'Choose exactly one platform.')
    if args.action == 'validate':
        return with_bundle(args, lambda manifest, directory: {'clip_id': manifest['clip_id'], 'validation': 'passed'})
    ledger = GitHubLedger.from_env()
    if args.action == 'init-state':
        ledger.initialize()
        return {'state': 'initialized_or_already_present', 'branch': ledger.BRANCH}
    ledger.load()
    if args.action == 'status':
        return {'records': [{k:v for k,v in r.items() if k in ['clip_id','platform','state','buffer_post_id','buffer_status','post_url','public_verified_at','media_deleted_at']}
                            for r in ledger.data['records'].values()]}
    if args.action == 'cleanup':
        return Engine(ledger, None, host_from_env()).cleanup(args.clip_id)
    engine = Engine(ledger, Buffer())
    if args.action == 'discover':
        return {'channels': engine.discover()}
    if args.action == 'reconcile':
        return summary(engine.reconcile(args.clip_id, args.platform, args.post_id))
    if args.action == 'confirm-public':
        return summary(engine.confirm_public(args.clip_id, args.platform, args.public_url))
    if args.action == 'publish':
        engine.host = host_from_env()
        channel = env('BUFFER_'+args.platform.upper()+'_CHANNEL_ID')
        return with_bundle(args, lambda manifest, directory: summary(engine.publish(
            manifest, directory, args.platform, channel, args.resume, args.confirm_unposted)))
    raise Stop('Unsupported action.')


def with_bundle(args, callback):
    # TemporaryDirectory is owned by this process; no user source directories are removed.
    with tempfile.TemporaryDirectory(prefix='motivtated-') as scratch:
        directory = Path(scratch)
        bundle = args.bundle
        if bundle is None:
            require(args.bundle_file_id, 'Provide a Google Drive bundle file ID or a local --bundle path.')
            bundle = directory/'input.zip'
            download_drive(args.bundle_file_id, bundle, args.bundle_sha256)
        content = directory/'content'
        content.mkdir()
        manifest = unpack(bundle, args.bundle_sha256, content)
        require(manifest['clip_id'] == args.clip_id, 'Selected clip ID does not match bundle.')
        return callback(manifest, content)


def summary(record):
    return {k:record.get(k) for k in ['clip_id','platform','state','buffer_post_id','buffer_status','post_url','public_verified_at']}


def main():
    parser = argparse.ArgumentParser(description='MOTIVTATED manual publisher. One clip, one platform, no scheduler.')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare', help='Create a validated private ZIP bundle locally.')
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--clip-id', required=True)
    p.add_argument('--output', type=Path, required=True)
    sub.add_parser('workflow', help='Read safely mapped GitHub Actions INPUT_* environment variables.')
    r = sub.add_parser('run')
    r.add_argument('--action', choices=ACTIONS, required=True)
    r.add_argument('--clip-id', default='')
    r.add_argument('--platform', choices=['tiktok','instagram'])
    r.add_argument('--bundle', type=Path)
    r.add_argument('--bundle-file-id', default='')
    r.add_argument('--bundle-sha256', default='')
    r.add_argument('--post-id')
    r.add_argument('--public-url', default='')
    r.add_argument('--resume', action='store_true')
    r.add_argument('--confirm-unposted', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(execute(args), indent=2, ensure_ascii=True))
    except Stop as e:
        parser.exit(2, f'STOP: {e}\n')
    except Exception as e:
        # Provider/library exceptions may contain signed URLs or credentials. Do not print them.
        parser.exit(2, f'STOP: Unexpected {type(e).__name__}. Inspect saved state before retrying; no automatic resubmission.\n')


if __name__ == '__main__':
    main()
