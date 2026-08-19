"""Exercise the provider layer: routing, fallback, metering, and the ceiling."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from loopback import config, llm, schema  # noqa: E402
from loopback.bots import personas  # noqa: E402


def main():
    schema.migrate()

    print("configured providers")
    print("-" * 60)
    for name, info in llm.status()["providers"].items():
        print("  %-10s configured=%-5s available=%-5s paid=%-5s  %s" % (
            name, info["configured"], info["available"], info["paid"], info["model"]))

    print("\nbudget")
    print("-" * 60)
    print("  ceiling  $%.2f" % config.LLM_BUDGET_USD)
    print("  spent    $%.4f" % llm.spent_usd(force=True))

    print("\nrouting (requested -> resolved)")
    print("-" * 60)
    for requested in ("openai", "gemini", "xai", "groq", "anthropic", "templates", None):
        print("  %-10s -> %-10s  (%s)" % (
            requested, llm.resolve(requested), llm.label(llm.resolve(requested))))

    print("\nlive generation, one line per house bot")
    print("-" * 60)
    for persona in personas.ALL:
        text, used = llm.line(
            persona.system,
            "Write one line about the hour just before dawn.",
            fallback="(fallback) the hour before dawn",
            provider=persona.provider,
            max_chars=110,
        )
        flag = "TEMPLATE" if used == llm.TEMPLATES else used.upper()
        print("  @%-10s [%-9s] %s" % (persona.handle, flag, text))

    print("\nspend after this run")
    print("-" * 60)
    spent = llm.spent_usd(force=True)
    print("  $%.6f of $%.2f  (%.3f%% of the ceiling)" % (
        spent, config.LLM_BUDGET_USD,
        100.0 * spent / config.LLM_BUDGET_USD if config.LLM_BUDGET_USD else 0.0))

    from loopback import db
    rows = db.query("""
        select provider, model, count(*) as calls,
               sum(input_tokens) as tin, sum(output_tokens) as tout,
               sum(est_cost_usd) as usd
          from @schema.llm_usage group by provider, model order by usd desc
    """)
    for row in rows:
        print("  %-10s %-22s %3s calls  %5s in / %4s out  $%s" % (
            row["provider"], row["model"], row["calls"],
            row["tin"], row["tout"], row["usd"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
