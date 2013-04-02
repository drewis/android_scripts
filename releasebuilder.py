#!/usr/bin/env python
# Andrew Sutherland <dr3wsuth3rland@gmail.com>

import argparse
from datetime import datetime
import logging as log
import os
import shutil
import subprocess as sp
import Queue

# local
from drewis import __version__
from drewis import html,rsync
from drewis.utils import *

# handle commandline args
parser = argparse.ArgumentParser(description="Drew's builder script")
parser.add_argument('--version', action='version', version='%(prog)s ' + __version__)
parser.add_argument('target', help="Device(s) to build",
                    nargs='+')
parser.add_argument('--source', help="Path to android tree",
                    default=os.getcwd())
parser.add_argument('--host', help="Hostname for upload")
parser.add_argument('--port', help="Listen port for host sshd")
parser.add_argument('--user', help="Username for upload host")
parser.add_argument('--remotedir', help="Remote path for uploads")
parser.add_argument('--localdir', help="Local path for uploads")
parser.add_argument('--nobuild', help=argparse.SUPPRESS,
                    action="store_true")
parser.add_argument('-q', '--quiet', help="Suppress all output",
                    action="store_true")
args = parser.parse_args()

# static vars
HELPER_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'helpers')
DATE = datetime.now().strftime('%Y.%m.%d')

# script logging
log_dir = os.path.join(args.source, 'release_logs')
if not os.path.isdir(log_dir):
    os.mkdir(log_dir)
scriptlog = os.path.join(log_dir, 'scriptlog-' + DATE + '.log')
log.basicConfig(filename=scriptlog, level=log.INFO,
        format='%(levelname)s:%(message)s')

def get_codename(target):
    codename = None
    for p,d,f in os.walk('device'):
        for dirs in d:
            if target == dirs:
                with open(os.path.join(p,dirs,'ev.mk')) as f:
                    contents = f.read().split('\n')
                    for line in contents:
                        if 'PRODUCT_CODENAME' in line:
                            codename = line.split(' ')[2]
    return codename

def main(args):

    # Info
    if not args.quiet:
        print 'Logging to %s' % scriptlog

    # for total runtime
    script_start = datetime.now()

    # set vars for uploading/mirroring
    if not args.user:
        droid_user = os.getenv('DROID_USER')
    else:
        droid_user = args.user
    if not args.host:
        droid_host = os.getenv('DROID_HOST')
    else:
        droid_host = args.host
    if not args.remotedir:
        droid_path = os.getenv('DROID_PATH')
    else:
        droid_path= args.remotedir
    if not args.localdir:
        droid_mirror = os.getenv('DROID_MIRROR')
        if not droid_mirror:
            droid_mirror = os.getenv('DROID_LOCAL_MIRROR')
    else:
        droid_mirror = args.localdir
    if not args.port:
        droid_host_port = os.getenv('DROID_HOST_PORT')
        if not droid_host_port:
            droid_host_port = '22'
    else:
        droid_host_port = args.port

    # we must put the builds somewhere
    if not droid_mirror:
        mirroring = False
        if droid_host and droid_user and droid_path:
            uploading = True
        else:
            log.error('DROID_MIRROR not set')
            log.error('DROID_HOST or DROID_USER or DROID_PATH not set')
            log.error('no where put builds. BAILING!!')
            if not args.quiet:
                print 'You must specify somewhere to put the builds. Exiting'
            exit()
    else:
        mirroring = True
        if droid_host and droid_user and droid_path:
            uploading = True
        else:
            uploading = False

    # cd working dir
    previous_working_dir = os.getcwd()
    os.chdir(args.source)

    if uploading:
        # upload path
        upload_path = droid_path
        # upload thread
        upq = Queue.Queue()
        t1 = rsync.rsyncThread(upq, port=droid_host_port, message='Uploaded')
        t1.setDaemon(True)
        t1.start()

    if mirroring:
        # mirror path
        mirror_path = droid_mirror
        # mirror thread
        m_q = Queue.Queue()
        t2 = rsync.rsyncThread(m_q, message='Mirrored')
        t2.setDaemon(True)
        t2.start()

    #
    # Building
    #

    # for zip storage
    if os.path.isdir('/dev/shm'):
        temp_dir = '/dev/shm/tmp-releasebuilder_zips'
    else:
        temp_dir = '/tmp/tmp-releasebuilder_zips'
    if not os.path.isdir(temp_dir):
        os.mkdir(temp_dir)

    # keep track of builds
    build_start = datetime.now()

    # build each target
    for target in args.target:
        os.putenv('EV_BUILD_TARGET', target)
        # Run the build: target will be pulled from env
        if not args.nobuild:
            try:
                with open(os.path.join(temp_dir,'build_stderr'), 'w') as build_stderr:
                    target_start = datetime.now()
                    sp.check_call([os.path.join(
                            HELPER_DIR, 'build.sh')],
                            stdout=build_stderr, stderr=sp.STDOUT)
            except sp.CalledProcessError as e:
                if not args.quiet:
                    print 'Build returned %d for %s' % (e.returncode, target)
                log.error('Build returned %d for %s' % (e.returncode, target))
                if not args.quiet:
                    handle_build_errors(os.path.join(temp_dir,'build_stderr'),
                            verbose=True)
                else:
                    handle_build_errors(os.path.join(temp_dir,'build_stderr'))
                continue
            else:
                if not args.quiet:
                    print('Built %s in %s' %
                            (target, pretty_time(datetime.now() - target_start)))
                log.info('Built %s in %s' %
                        (target, pretty_time(datetime.now() - target_start)))
        # find and add the zips to the rsync queues
        zips = []
        target_out_dir = os.path.join('out', 'target', 'product', target)
        if os.path.isdir(target_out_dir):
            for f in os.listdir(target_out_dir):
                if f.startswith('Evervolv') and f.endswith('.zip'):
                    zips.append(f)
        if zips:
            codename = get_codename(target)
            if codename:
                if uploading:
                    # make the remote directories
                    try:
                        sp.check_call(['ssh', '-p%s' % (droid_host_port),
                                '%s@%s' % (droid_user, droid_host),
                                'test -d %s || mkdir -p %s' % (os.path.join(upload_path,
                                codename),os.path.join(upload_path, codename))])
                    except sp.CalledProcessError as e:
                        if not args.quiet:
                            print('ssh returned %d while making directories' %
                                    (e.returncode))
                        log.error('ssh returned %d while making directories' %
                                (e.returncode))

                if mirroring:
                    try:
                        if not os.path.isdir(os.path.join(mirror_path, codename)):
                            os.makedirs(os.path.join(mirror_path, codename))
                    except OSError as e:
                        log.error('failed to make mirror dir: %s' % (e))

                for z in zips:
                    shutil.copy(os.path.join(target_out_dir, z),
                            os.path.join(temp_dir, z))
                    if uploading:
                        upq.put((os.path.join(temp_dir, z),
                                '%s@%s:%s' % (droid_user, droid_host,
                                os.path.join(upload_path, codename))))
                    if mirroring:
                        m_q.put((os.path.join(temp_dir, z),
                                os.path.join(mirror_path, codename)))
            else:
                if not args.quiet:
                    print 'Failed to get codename for %s' % (target)
                log.error('Failed to get codename for %s' % (target))
        else:
            if not args.quiet:
                print 'No zips found for %s' % (target)
            log.warning('No zips found for %s' % target)

    # write total buildtime
    if not args.quiet:
        print('Built all targets in %s' %
                (pretty_time(datetime.now() - build_start)))
    log.info('Built all targets in %s' %
            (pretty_time(datetime.now() - build_start)))

    # wait for builds to finish uploading/mirroring
    if mirroring:
        m_q.join()
    if uploading:
        upq.join()

    # cleanup
    shutil.rmtree(temp_dir)

    if not args.quiet:
        print('Total run time: %s' %
                (pretty_time(datetime.now() - script_start)))
    log.info('Total run time: %s' %
            (pretty_time(datetime.now() - script_start)))

    # cd previous working dir
    os.chdir(previous_working_dir)

if __name__ == "__main__":
    main(args)
