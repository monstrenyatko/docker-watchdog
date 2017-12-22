#!/usr/bin/env python3

import sys
import time
import logging.config
import argparse
import docker.errors


logging.config.dictConfig(
    {
        'version': 1,
        'disable_existing_loggers': True,
        'formatters': {
            'verbose': {
                'format': '%(asctime)s [%(name)s][%(process)d]: [%(levelname)s] %(message)s',
            },
            'syslog': {
                'format': '%(name)s[%(process)d]: [%(levelname)s] %(message)s',
            },
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'stream': sys.stdout,
                'formatter': 'verbose',
            },
            'syslog': {
                'class': 'logging.handlers.SysLogHandler',
                'facility': 'daemon',
                'level': logging.INFO,
                'formatter': 'syslog',
            },
        },
        'root': {
            'handlers': ['console', 'syslog'],
        },
    }
)
LOG = logging.getLogger('docker-daemon-monitor')
LOG.setLevel(logging.DEBUG)


def dict_remove_none(input_dict):
    return {k:v for k,v in input_dict.items() if v!=None}


def get_docker_version(client):
    try:
        return client.version().get('Version')
    except:
        return None


def connect_docker_service(attempts_qty, attempts_tm_sec):
    client = docker.from_env()
    # Verify Docker service connection
    version = None
    for i in range(0, attempts_qty):
        version = get_docker_version(client)
        if version:
            break
        LOG.warn("Can't get Docker version")
        if i+1 < attempts_qty:
            LOG.info('Retry in: %d sec', attempts_tm_sec)
            time.sleep(attempts_tm_sec)
    if version:
        LOG.info('Docker version: %s', version)
    else:
        LOG.error("Can't get Docker version")
        client = None
    return client


def restart_docker():
    LOG.info('Restarting Docker service')
    from dbus import SystemBus, Interface
    from dbus.exceptions import DBusException
    #
    dbus_systemd_name = 'org.freedesktop.systemd1'
    dbus_systemd_path = '/org/freedesktop/systemd1'
    systemd_docker_name = 'docker.service'
    #
    try:
        systemd = SystemBus().get_object(dbus_systemd_name, dbus_systemd_path)
        systemd_manager = Interface(systemd, dbus_interface=dbus_systemd_name+'.Manager')
        systemd_manager.RestartUnit(systemd_docker_name, 'fail')
    except DBusException as e:
        LOG.error("Can't restart Docker, error: %s", e)
        LOG.debug('Exception', exc_info=1)


def verify_docker_client(client, restart=False):
    if not client:
        LOG.error('Docker service is not available => exit' + (' and restart service' if restart else ''))
        if restart:
            restart_docker()
        exit()


if __name__ == '__main__':
    ## Process command-line options
    cmd_parser = argparse.ArgumentParser(
        description="""
        Monitors Docker service health.
        Restarts Docker daemon if not running.
        Starts specified containers if not running.
        """
    )
    cmd_parser.add_argument(
        '--attempts-qty', nargs='?', type=int, choices=range(1,6), default=3,
        help='Number of attempts/checks before the fail decision (default: %(default)s).',
    )
    cmd_parser.add_argument(
        '--attempts-timeout', nargs='?', type=int, default=30,
        help='Delay in seconds before the next attempt (default: %(default)s).',
    )
    cmd_parser.add_argument(
        '-c', '--container', action='append',
        help='Container name to monitor and start. May be specified multiple times.',
        default=[],
    )
    cmd_parser.add_argument(
        '-cfn', '--container-filter-name', action='append',
        help='''
        Same as --container but allows specifying the just chunk of the container name.
        Useful to match multiple containers with similar name.
        May be specified multiple times.
        ''',
        default=[],
    )
    cmd_options = vars(cmd_parser.parse_args())
    attempts_qty = cmd_options.get('attempts_qty')
    attempts_tm_sec = cmd_options.get('attempts_timeout')
    docker_container_check_list = cmd_options.get('container')
    docker_container_filter_name_check_list = cmd_options.get('container_filter_name')


    ## Connect to Docker service
    docker_client = connect_docker_service(attempts_qty, attempts_tm_sec)
    verify_docker_client(docker_client, restart=True)
    ## Docker service is available


    ## Restart Docker service if it fails to start all containers on system boot
    # May happens on 17.11.0
    docker_container_qty = None
    docker_container_running_qty = None
    for i in range(0, attempts_qty):
        docker_info = docker_client.info()
        docker_container_qty = docker_info.get('Containers')
        docker_container_running_qty = docker_info.get('ContainersRunning')
        LOG.info('Containers info, qty: %d, running: %d', docker_container_qty, docker_container_running_qty)
        if docker_container_qty == 0 or (docker_container_qty > 0 and docker_container_running_qty > 0):
            break
        LOG.warn('Docker has zero qty of running containers')
        if i+1 < attempts_qty:
            LOG.info('Wait for %d sec', attempts_tm_sec)
            time.sleep(attempts_tm_sec)
    if docker_container_qty > 0 and docker_container_running_qty == 0:
        LOG.error('Docker failed to start containers')
        restart_docker()
        docker_client = connect_docker_service(attempts_qty, attempts_tm_sec)
        verify_docker_client(docker_client)


    ## Restart containers if not running
    docker_container_start_list = {}
    # Get containers objects
    for i in docker_container_check_list:
        try:
            container = docker_client.containers.get(i)
            docker_container_start_list[container.name] = container
        except docker.errors.NotFound:
            LOG.warn('Docker container is not found, name: %s => skip', i)
        except docker.errors.APIError as e:
            LOG.error("Can't get Docker container, name: %s, error: %s", i, e)
            LOG.debug('Exception', exc_info=1)
    # Get containers objects by filter-name
    for i in docker_container_filter_name_check_list:
        try:
            containers = docker_client.containers.list(all=True, filters={'name':i})
            if len(containers) == 0:
                LOG.warn('Docker containers are not found, filter-name: %s => skip', i)
            for v in containers:
                docker_container_start_list[v.name] = v
        except docker.errors.APIError as e:
            LOG.error("Can't get Docker containers list, filter-name: %s, error: %s", i, e)
            LOG.debug('Exception', exc_info=1)
    # Clean-up the list
    docker_container_start_list = dict_remove_none(docker_container_start_list)
    #
    LOG.info('Monitored containers: %s', list(docker_container_start_list.keys()))
    # Ignore running or starting containers
    for i in range(0, attempts_qty if len(docker_container_start_list)>0 else 0):
        # Check status
        for k,v in docker_container_start_list.items():
            v.reload()
            if v.status == 'running':
                docker_container_start_list[k] = None
        # Clean-up the list
        docker_container_start_list = dict_remove_none(docker_container_start_list)
        # Check the list size
        if len(docker_container_start_list) == 0:
            # All available containers are running
            break
        LOG.info('Found not running containers, list: %s', list(docker_container_start_list.keys()))
        if i+1 < attempts_qty:
            LOG.info('Wait for %d sec', attempts_tm_sec)
            time.sleep(attempts_tm_sec)
    # Starting not running containers
    for k,v in docker_container_start_list.items():
        LOG.info('Starting container, name: %s', k)
        try:
            v.start()
        except docker.errors.APIError as e:
            LOG.error("Can't start container, name: %s, error: %s", k, e)
            LOG.debug('Exception', exc_info=1)
