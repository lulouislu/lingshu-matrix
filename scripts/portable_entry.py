"""PyInstaller entry point; retain the regular CLI and Ctrl+C lifecycle."""
import multiprocessing
import json
from pathlib import Path
import ssl
import sys

from macnet.cli import main


if __name__ == "__main__":
    multiprocessing.freeze_support()
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if sys.argv[1:] == ["--check-runtime"]:
        import keyring
        import macnet
        context = ssl.create_default_context()
        assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
        backend = type(keyring.get_keyring())
        assert backend.__module__ == "keyring.backends.Windows" and backend.__name__ == "WinVaultKeyring"
        assert (Path(macnet.__file__).parent / "static/index.html").is_file()
        print(json.dumps({"tls": ssl.OPENSSL_VERSION, "certificate_verification": True,
                          "credential_backend": backend.__module__ + "." + backend.__name__,
                          "frontend": True}))
    else:
        raise SystemExit(main())
