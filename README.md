DOCKER WATCHDOG
===============


About
=====

This project contains scripts to restart [Docker](https://www.docker.com/) service and containers in case of `Docker` daemon failure.


Preconditions
=============

Linux
-----

- Distribution with installed [systemd](https://www.freedesktop.org/wiki/Software/systemd/)
- `Docker` daemon managed by the `systemd`

Python
------

- [Python](https://www.python.org/) `3`
- [pip](https://pip.pypa.io) for `Python 3`
- `D-Bus` library for `Python 3`
- Additional `Python` packages:

  ```sh
  pip3 install -r requirements.txt
  ```


Usage
=====

CRON
----

Execute every 30 minutes using `crontab`.
Edit `root` `crontab`:

```sh
sudo crontab -e
```

Add new line like:

```
*/30 * * * * /root/bin/docker-watchdog/daemon_monitor.py > /dev/null 2>&1
```
