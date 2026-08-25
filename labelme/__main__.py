from __future__ import annotations

import argparse
import io
import os
import sys
import traceback
import types
import webbrowser
from pathlib import Path
from typing import AnyStr
from typing import Final

from loguru import logger

from labelme import __appname__
from labelme import __version__

from . import _config
from . import _yaml
from ._label_file import is_label_file_path
from ._webapp import bind_requires_access_token
from ._webapp import build_session
from ._webapp import create_app

_LOGGER_LEVELS: Final = ("debug", "info", "warning", "error", "critical")


class _LoggerIO(io.StringIO):
    def write(self, s: AnyStr) -> int:
        assert isinstance(s, str)
        if stripped_s := s.strip():
            logger.debug(stripped_s)
        return len(s)

    def readable(self) -> bool:
        return False

    def seekable(self) -> bool:
        return False


def _setup_loguru(logger_level: str) -> None:
    logger.remove()

    if sys.stderr:
        logger.add(sys.stderr, level=logger_level)

    try:
        if os.name == "nt":
            cache_dir = Path(os.environ["LOCALAPPDATA"]) / "labelme"
        else:
            cache_dir = Path("~/.cache/labelme").expanduser()

        cache_dir.mkdir(parents=True, exist_ok=True)

        log_file = cache_dir / "labelme.log"
        logger.add(
            log_file,
            colorize=True,
            level="DEBUG",
            rotation="10 MB",
            retention="30 days",
            compression="gz",
            enqueue=True,
            backtrace=True,
            diagnose=True,
        )
    except Exception as e:
        logger.warning(
            "Failed to set up the log file, logging to stderr only: {}: {}",
            type(e).__name__,
            e,
        )


def _handle_exception(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_traceback: types.TracebackType | None,
) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        sys.exit(0)

    traceback_str: str = "".join(
        traceback.format_exception(exc_type, exc_value, exc_traceback)
    )
    logger.critical(traceback_str)
    sys.exit(1)


class _DeprecatedAlias(argparse.Action):
    """Store the value, but FutureWarning when a deprecated alias spelling is used.

    The canonical option string is the first one registered; any other spelling
    argparse matched (including abbreviations) warns and points back to it.
    """

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        canonical = self.option_strings[0]
        if option_string is not None and option_string != canonical:
            import warnings

            warnings.warn(
                f"{option_string} is deprecated and will be removed in a future "
                f"version. Use {canonical} instead.",
                FutureWarning,
                stacklevel=1,
            )
        setattr(namespace, self.dest, self.const if self.nargs == 0 else values)


def _parse_list_arg(value: str) -> list[str]:
    if os.path.isfile(value):
        with open(value, encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    return [line.strip() for line in value.split(",") if line.strip()]


def _resolve_config_source(
    config_arg: str | None, default_config_file: str
) -> tuple[Path | None, dict]:
    if config_arg is None:
        if not os.path.isfile(default_config_file):
            logger.warning(
                "Config file does not exist: {!r}; using the default settings",
                str(Path(default_config_file).absolute()),
            )
            return None, {}
        return Path(default_config_file), {}

    if isinstance(config_loaded := _yaml.safe_load(config_arg), dict):
        return None, config_loaded

    if not os.path.isfile(config_arg):
        logger.error(
            "Config file does not exist: {!r}", str(Path(config_arg).absolute())
        )
        sys.exit(1)
    return Path(config_arg), {}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", "-V", action="store_true", help="show version")
    parser.add_argument(
        "--reset-config",
        action="store_true",
        help="ignored; kept for CLI compatibility (window state is no longer stored)",
    )
    parser.add_argument(
        "--logger-level",
        default="debug",
        choices=_LOGGER_LEVELS,
        help="logger level",
    )
    parser.add_argument("path", nargs="?", help="image file, label file, or directory")
    parser.add_argument(
        "--output",
        help="output directory for saving annotation JSON files",
    )
    default_config_file = _config.get_user_config_file()
    parser.add_argument(
        "--config",
        dest="config",
        help=f"config file or yaml-format string (default: {default_config_file})",
        default=None,
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="host interface for the local web service (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="port for the local web service (default: 8080)",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="do not open a browser window",
    )
    parser.add_argument(
        "--access-token",
        default=None,
        help=(
            "require Authorization: Bearer for /api routes; generated automatically "
            "when --host is not a loopback address"
        ),
    )
    parser.add_argument(
        "--with-image-data",
        dest="with_image_data",
        action="store_true",
        help="store image data in JSON file",
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--no-auto-save",
        dest="auto_save",
        action="store_false",
        help="disable auto save",
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--no-sort-labels",
        "--nosortlabels",  # deprecated
        dest="sort_labels",
        action=_DeprecatedAlias,
        nargs=0,
        const=False,
        help="stop sorting labels",
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--flags",
        help="comma separated list of flags OR file containing flags",
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--label-flags",
        "--labelflags",  # deprecated
        dest="label_flags",
        action=_DeprecatedAlias,
        help=r"yaml string of label specific flags OR file containing json "
        r"string of label specific flags (ex. {person-\d+: [male, tall], "
        r"dog-\d+: [black, brown, white], .*: [occluded]})",
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--labels",
        help="comma separated list of labels OR file containing labels",
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--validate-label",
        "--validatelabel",  # deprecated
        dest="validate_label",
        action=_DeprecatedAlias,
        choices=["exact"],
        help="label validation types",
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--keep-prev",
        action="store_true",
        help="keep annotation of previous frame",
        default=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--epsilon",
        type=float,
        help="epsilon to find nearest vertex on canvas",
        default=argparse.SUPPRESS,
    )
    args = parser.parse_args(argv)
    if args.output is not None and is_label_file_path(filename=args.output):
        parser.error(
            f"--output expects a directory path, but '{args.output}' looks like a file."
            " Remove the .json extension or provide a directory path."
        )
    return args


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    if args.version:
        print(f"{__appname__} {__version__}")
        sys.exit(0)

    _setup_loguru(logger_level=args.logger_level.upper())
    logger.info("Starting {} {}", __appname__, __version__)

    sys.excepthook = _handle_exception

    if hasattr(args, "flags"):
        args.flags = _parse_list_arg(args.flags)

    if hasattr(args, "labels"):
        args.labels = _parse_list_arg(args.labels)

    if hasattr(args, "label_flags"):
        if os.path.isfile(args.label_flags):
            with open(args.label_flags, encoding="utf-8") as f:
                args.label_flags = _yaml.safe_load(f)
        else:
            args.label_flags = _yaml.safe_load(args.label_flags)

    config_from_args = vars(args).copy()
    config_from_args.pop("version")
    reset_config = config_from_args.pop("reset_config")
    file_or_dir = config_from_args.pop("path")
    output = config_from_args.pop("output")
    config_from_args.pop("logger_level")
    host = config_from_args.pop("host")
    port = config_from_args.pop("port")
    no_browser = config_from_args.pop("no_browser")
    access_token = config_from_args.pop("access_token")

    config_file, config_overrides = _resolve_config_source(
        config_arg=config_from_args.pop("config"),
        default_config_file=_config.get_user_config_file(),
    )
    config_overrides.update(config_from_args)

    output_dir = Path(output) if output is not None else None

    if reset_config:
        logger.info("--reset-config is ignored: the web UI does not store window state")

    session = build_session(
        config_file=config_file,
        config_overrides=config_overrides,
        file_or_dir=file_or_dir,
        output_dir=output_dir,
    )
    if not access_token and bind_requires_access_token(host):
        import secrets

        access_token = secrets.token_urlsafe(24)
    app = create_app(session=session, access_token=access_token)

    url = f"http://{host}:{port}"
    if access_token:
        url = f"{url}/?token={access_token}"
        logger.warning(
            "API requests require Authorization: Bearer (token printed in the URL)"
        )
    logger.info("Serving Labelme at {}", url)
    print(f"{__appname__} {__version__}")
    print(f"Open {url} in your browser")
    if access_token and bind_requires_access_token(host):
        print(
            "This bind is not loopback-only; keep the token private. "
            "API routes reject requests without it."
        )
    if not no_browser:
        webbrowser.open(url)

    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
