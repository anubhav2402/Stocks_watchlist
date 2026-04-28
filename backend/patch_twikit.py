"""
Post-install patch for twikit==1.7.6
Fixes KeyErrors caused by optional/missing fields in Twitter API responses.
Run once after: pip install twikit==1.7.6
"""
import importlib.util, pathlib, sys, re

def find_twikit_user_file():
    spec = importlib.util.find_spec("twikit")
    if spec is None:
        print("twikit not installed — skipping patch")
        sys.exit(0)
    pkg_dir = pathlib.Path(spec.origin).parent
    return pkg_dir / "user.py"

def patch(path: pathlib.Path):
    src = path.read_text()
    original = src

    # Fix 1: description urls — optional field
    src = src.replace(
        "legacy['entities']['description']['urls']",
        "legacy['entities']['description'].get('urls', [])"
    )
    # Fix 2: pinned_tweet_ids_str — not always present
    src = re.sub(
        r"legacy\['pinned_tweet_ids_str'\]",
        "legacy.get('pinned_tweet_ids_str', [])",
        src
    )
    # Fix 3: withheld_in_countries — not always present
    src = re.sub(
        r"legacy\['withheld_in_countries'\]",
        "legacy.get('withheld_in_countries', [])",
        src
    )

    if src == original:
        print("twikit/user.py — already patched or no matches found")
    else:
        path.write_text(src)
        print(f"twikit/user.py patched successfully ({path})")

if __name__ == "__main__":
    user_file = find_twikit_user_file()
    patch(user_file)
