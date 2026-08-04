"""Charge/discharge (Neware) triggers — built on top of NewareClient."""
import datetime


def start_channels(neware, channels, protocol, savedir, backup=None, skip=()):
    """Start the charge/discharge protocol on a range of channels. Returns the list of started channel indices."""
    backup = backup or (savedir + "remote_dir/")
    today = datetime.datetime.now().strftime("%y%m%d")
    started = []
    for i in channels:
        if i in skip:
            continue
        sub, chl = neware.index_to_subchl(i)
        neware.start(sub, chl, protocol, savedir, f"{today}_{sub}-{chl}", backup)
        started.append(i)
    return started


def continue_channel(neware, ch):
    sub, chl = neware.index_to_subchl(ch)
    return neware.continue_(sub, chl)


def pause_channels(neware, channels, skip=()):
    """Pause a range of channels (BTS pause). Resumable via 'continue'. Returns the list of paused indices."""
    paused = []
    for i in channels:
        if i in skip:
            continue
        sub, chl = neware.index_to_subchl(i)
        neware.pause(sub, chl)
        paused.append(i)
    return paused


def status(neware, ch):
    sub, chl = neware.index_to_subchl(ch)
    return neware.status(sub, chl)


def status_all(neware):
    return neware.status_all()
