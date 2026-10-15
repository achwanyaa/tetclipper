"""Studio on Modal: analyse a downloaded slice on a GPU and render specs on
many CPUs, driven from this PC with the Modal SDK.

  remote.py  runs inside the Modal functions (see pipeline/modal_app.py)
  client.py  runs here: upload to the volume, call the function, pull back

The PC always downloads from YouTube (Modal's datacenter IPs are bot-blocked)
and keeps the media, so the editor previews locally with no round trip.
"""

APP_NAME = "tetclipper"
VOLUME_NAME = "tetclipper-home"
REMOTE_HOME = "/data"
