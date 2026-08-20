import faulthandler
import threading


def _dump():
    faulthandler.dump_traceback()
threading.Timer(30.0, _dump).start()
