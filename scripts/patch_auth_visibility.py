"""Do not let a bad credential look like a quiet bot.

@my_bot had its runner key written with the wrong secret, so every call it made
returned 401. The scheduler logged four clean runs, recorded no error, and the
bot simply produced nothing -- indistinguishable from a bot whose dice came up
short. The clue was last_seen_at staying null while runs climbed, which nobody
would think to look at.

A 401 is not a normal outcome for a bot the platform is driving. It means the
credential is wrong and every future turn will fail the same way, so it is now
raised rather than debug-logged: the tick loop records it against the program
and it shows up in last_error where someone will see it.
"""
import pathlib

root = pathlib.Path(__file__).resolve().parent.parent
r = root / "loopback" / "bots" / "runtime.py"
s = r.read_text(encoding="utf-8")

# Every place a LoopbackError is swallowed, let an auth failure through.
GUARD = '''

class CredentialError(RuntimeError):
    """This bot's key does not work. Every turn will fail until it is fixed."""


def _check_auth(exc, persona):
    """Re-raise a 401 as something the tick loop will record.

    Rate limits and transient failures are ordinary and worth ignoring. A 401
    is not: it means the stored credential is wrong, which no amount of waiting
    repairs, and swallowing it makes a misconfigured bot look merely quiet.
    """
    if getattr(exc, "status", None) == 401:
        raise CredentialError(
            "@%s cannot authenticate -- its stored key does not match the "
            "secret this server derives from. It will do nothing until the "
            "runner key is rewritten." % persona.handle
        )

'''

s = s.replace("# --- one bot's turn ---", GUARD.strip("\n") + "\n\n\n# --- one bot's turn ---", 1)

# Post
s = s.replace(
    '''        except LoopbackError as exc:
            if exc.rate_limited:
                log.debug("@%s hit its post budget", persona.handle)
            else:
                log.warning("@%s could not post: %s", persona.handle, exc)''',
    '''        except LoopbackError as exc:
            _check_auth(exc, persona)
            if exc.rate_limited:
                log.debug("@%s hit its post budget", persona.handle)
            else:
                log.warning("@%s could not post: %s", persona.handle, exc)''',
)

# Comment
s = s.replace(
    '''            except LoopbackError as exc:
                log.debug("@%s could not comment: %s", persona.handle, exc)
                with _state_lock:
                    _commented.discard(key)''',
    '''            except LoopbackError as exc:
                _check_auth(exc, persona)
                log.debug("@%s could not comment: %s", persona.handle, exc)
                with _state_lock:
                    _commented.discard(key)''',
)

# React
s = s.replace(
    '''        except LoopbackError as exc:
            log.debug("@%s could not react: %s", persona.handle, exc)''',
    '''        except LoopbackError as exc:
            _check_auth(exc, persona)
            log.debug("@%s could not react: %s", persona.handle, exc)''',
)

# Follow
s = s.replace(
    '''            except LoopbackError as exc:
                log.debug("@%s could not follow: %s", persona.handle, exc)''',
    '''            except LoopbackError as exc:
                _check_auth(exc, persona)
                log.debug("@%s could not follow: %s", persona.handle, exc)''',
)

r.write_text(s, encoding="utf-8")
print("runtime.py: 401s surface instead of being swallowed")

# --- activate_bot: refuse to write a key with the wrong secret ------------
a = root / "scripts" / "activate_bot.py"
s = a.read_text(encoding="utf-8")

s = s.replace(
    '''def main():
    targets = [a for a in sys.argv[1:] if not a.startswith("--")]
    confirmed = "--yes" in sys.argv''',
    '''def main():
    targets = [a for a in sys.argv[1:] if not a.startswith("--")]
    confirmed = "--yes" in sys.argv

    # The runner key is derived from HOUSE_BOT_SECRET. Writing one here with a
    # different secret than the server uses produces a bot that authenticates
    # nowhere and fails silently, which is exactly the bug this script was
    # written to clean up after.
    import os
    if confirmed and not os.environ.get("HOUSE_BOT_SECRET"):
        print("HOUSE_BOT_SECRET is not set.")
        print("Without it the derived runner key will not match the server's,")
        print("and the bot will 401 on every action while looking merely quiet.")
        print("Re-run with the same HOUSE_BOT_SECRET the deployment uses.")
        return 1''',
)

a.write_text(s, encoding="utf-8")
print("activate_bot.py: refuses to write a mismatched key")

for f, marker in ((r, "_check_auth"), (a, "HOUSE_BOT_SECRET is not set")):
    print("  %-18s %s" % (f.name, "ok" if marker in f.read_text(encoding="utf-8") else "MISSING"))
