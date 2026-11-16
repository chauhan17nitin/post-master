#!/bin/sh
# post-master installer.
#
#   curl -fsSL https://raw.githubusercontent.com/chauhan17nitin/post-master/master/install.sh | sh
#
# Puts the `post-master` command on your PATH and the api-testing skill into ~/.claude/skills/.
# Run it again to update. Needs python3 (3.8+) and jq; nothing else.
#
# Optional settings (environment variables):
#   POST_MASTER_REF    branch, tag or commit to install     (default: the latest release)
#   POST_MASTER_HOME   where the files are kept             (default: ~/.post-master)
#   POST_MASTER_BIN    where the command is linked          (default: ~/.local/bin)
#   CLAUDE_SKILLS_DIR  where the skill is linked            (default: ~/.claude/skills)
#   POST_MASTER_URL    tarball to install instead of GitHub (for testing; file:// works)

set -eu

REPO="chauhan17nitin/post-master"
REF="${POST_MASTER_REF:-}"          # empty: resolved to the latest release in pick_version
HOME_DIR="${POST_MASTER_HOME:-$HOME/.post-master}"
BIN_DIR="${POST_MASTER_BIN:-$HOME/.local/bin}"
SKILLS_DIR="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"

SKILL_REL="skills/api-testing"
SCRIPT_REL="$SKILL_REL/scripts/post_master.py"

say()  { printf '%s\n' "$*"; }
fail() { printf 'post-master install: %s\n' "$*" >&2; exit 1; }

check_requirements() {
  missing=""
  for tool in curl tar python3 jq; do
    command -v "$tool" >/dev/null 2>&1 || missing="$missing $tool"
  done
  if [ -n "$missing" ]; then
    say "Missing:$missing"
    case "$missing" in *jq*)
      say "  jq:      macOS  brew install jq   |   Debian/Ubuntu  sudo apt install jq" ;;
    esac
    case "$missing" in *python3*)
      say "  python3: macOS  xcode-select --install  (or brew install python)   |   Debian/Ubuntu  sudo apt install python3" ;;
    esac
    fail "install the tools above, then run this again. Nothing was changed."
  fi
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' \
    || fail "python3 is older than 3.8. Nothing was changed."
}

pick_version() {
  [ -z "$REF" ] || return 0
  # github.com/<repo>/releases/latest redirects to …/releases/tag/<tag>; the last path part is the tag.
  latest="$(curl -fsSLI -o /dev/null -w '%{url_effective}' "https://github.com/$REPO/releases/latest" 2>/dev/null || true)"
  case "$latest" in
    */releases/tag/*) REF="${latest##*/}" ;;
    *) fail "could not find the latest release of $REPO. Check your connection, or set POST_MASTER_REF. Nothing was changed." ;;
  esac
}

download() {
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  say "Downloading post-master (${REF:-local file})…"
  curl -fsSL "${POST_MASTER_URL:-https://github.com/$REPO/archive/$REF.tar.gz}" -o "$TMP/src.tar.gz" \
    || fail "download failed (is '$REF' a real branch or tag of $REPO?). Nothing was changed."
  mkdir "$TMP/src"
  tar -xzf "$TMP/src.tar.gz" -C "$TMP/src" --strip-components=1
  [ -f "$TMP/src/$SCRIPT_REL" ] || fail "the download does not look like post-master. Nothing was changed."
}

install_files() {
  # Only ever replace a folder that is a previous post-master install.
  if [ -e "$HOME_DIR" ]; then
    [ -f "$HOME_DIR/$SCRIPT_REL" ] \
      || fail "$HOME_DIR exists and is not a post-master install. Move it away or set POST_MASTER_HOME."
    rm -rf "$HOME_DIR"
  fi
  mkdir -p "$(dirname "$HOME_DIR")"
  mv "$TMP/src" "$HOME_DIR"
  chmod +x "$HOME_DIR/$SCRIPT_REL"
}

link_skill() {
  target="$SKILLS_DIR/api-testing"
  mkdir -p "$SKILLS_DIR"
  if [ -L "$target" ]; then
    rm "$target"                                   # an old link (ours or a dev checkout): repoint it
  elif [ -e "$target" ]; then
    backup="$target.backup-$(date +%Y%m%d-%H%M%S)" # a real folder: keep it, never delete
    mv "$target" "$backup"
    say "Kept your existing skill folder as $backup"
  fi
  ln -s "$HOME_DIR/$SKILL_REL" "$target"
}

link_command() {
  target="$BIN_DIR/post-master"
  mkdir -p "$BIN_DIR"
  if [ -e "$target" ] && [ ! -L "$target" ]; then
    fail "$target exists and is not a link. Remove it or set POST_MASTER_BIN, then run this again."
  fi
  ln -sf "$HOME_DIR/$SCRIPT_REL" "$target"
}

report() {
  version="$("$BIN_DIR/post-master" --version 2>/dev/null || true)"
  [ -n "$version" ] || version="post-master"
  say ""
  say "Installed $version"
  say "  command  $BIN_DIR/post-master"
  say "  skill    $SKILLS_DIR/api-testing"
  say "  files    $HOME_DIR"
  case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
      say ""
      say "$BIN_DIR is not on your PATH. Add this line to your shell profile (~/.zshrc or ~/.bashrc):"
      say "  export PATH=\"$BIN_DIR:\$PATH\""
      ;;
  esac
  say ""
  say "Next: ask Claude Code to test an API, then review with:  post-master serve"
}

main() {
  check_requirements
  [ -n "${POST_MASTER_URL:-}" ] || pick_version
  download
  install_files
  link_skill
  link_command
  report
}

# Everything is inside functions so a cut-off download cannot run half a script.
main
