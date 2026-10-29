#!/usr/bin/env bash
# Shared helpers for smg-dev-guide scripts and hooks. Source this file; do not execute it.
#
#   smg_root [dir]        print the SMG checkout root that contains dir (default: cwd), else return 1
#   guide_repo_root [dir] print the smg-dev-guide checkout root that contains dir, else return 1
#   guide_root            print the installed plugin/guide root (CLAUDE_PLUGIN_ROOT, else this repo)
#   smg_version <root>    the gateway crate version from model_gateway/Cargo.toml
#   smg_head <root>       short HEAD sha of a checkout
#   guide_pin             the SMG commit the guide was last verified against (smg-ref.json)
#   guide_pin_version     the SMG version the guide was last verified against

smg_root() {
  local d
  d="$(cd "${1:-.}" 2>/dev/null && pwd -P)" || return 1
  while [ -n "$d" ]; do
    if [ -f "$d/model_gateway/Cargo.toml" ] && [ -f "$d/crates/protocols/Cargo.toml" ]; then
      printf '%s\n' "$d"
      return 0
    fi
    [ "$d" = "/" ] && return 1
    d="$(dirname "$d")"
  done
  return 1
}

guide_repo_root() {
  local d
  d="$(cd "${1:-.}" 2>/dev/null && pwd -P)" || return 1
  while [ -n "$d" ]; do
    if [ -f "$d/.claude-plugin/plugin.json" ] && [ -f "$d/skills/map/SKILL.md" ] && [ -f "$d/smg-ref.json" ]; then
      printf '%s\n' "$d"
      return 0
    fi
    [ "$d" = "/" ] && return 1
    d="$(dirname "$d")"
  done
  return 1
}

guide_root() {
  if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -d "${CLAUDE_PLUGIN_ROOT}/skills" ]; then
    printf '%s\n' "${CLAUDE_PLUGIN_ROOT}"
  else
    cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P
  fi
}

smg_version() {
  sed -nE 's/^version *= *"([^"]+)".*/\1/p' "$1/model_gateway/Cargo.toml" 2>/dev/null | head -1
}

smg_head() {
  git -C "$1" rev-parse --short=12 HEAD 2>/dev/null
}

guide_pin() {
  sed -nE 's/.*"verified_commit" *: *"([0-9a-f]+)".*/\1/p' "$(guide_root)/smg-ref.json" 2>/dev/null | head -1
}

guide_pin_version() {
  sed -nE 's/.*"verified_version" *: *"([^"]+)".*/\1/p' "$(guide_root)/smg-ref.json" 2>/dev/null | head -1
}
