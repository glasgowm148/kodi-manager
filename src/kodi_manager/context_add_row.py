"""Context menu: "Add to Kodi Manager cached rows" on any video add-on folder."""
import sys


def main():
    import xbmc
    import xbmcgui
    import xbmcvfs
    try:
        from .widget_rows import add_from_context
    except ImportError:
        from widget_rows import add_from_context
    add_from_context(xbmc, xbmcgui, xbmcvfs, getattr(sys, "listitem", None))


if __name__ == "__main__":
    main()
