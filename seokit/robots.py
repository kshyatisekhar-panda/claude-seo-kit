"""robots.txt parsing and checks, following RFC 9309.

- Groups start with one or more user-agent lines; a crawler uses the group
  whose product token matches it, otherwise the "*" group.
- The longest matching path rule wins; on a tie, allow wins.
- "*" matches any sequence of characters and a trailing "$" anchors the end.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import quote, unquote, urlsplit

# Crawlers and control tokens that decide how AI products may use a site.
# purpose: "search" = cited answers with links, "user" = fetched when a person
# asks an assistant, "training" = model training, "control" = a robots token
# only, never seen in logs.
AI_AGENTS = [
    ("GPTBot", "OpenAI", "training"),
    ("OAI-SearchBot", "OpenAI", "search"),
    ("ChatGPT-User", "OpenAI", "user"),
    ("ClaudeBot", "Anthropic", "training"),
    ("Claude-SearchBot", "Anthropic", "search"),
    ("Claude-User", "Anthropic", "user"),
    ("PerplexityBot", "Perplexity", "search"),
    ("Perplexity-User", "Perplexity", "user"),
    ("Google-Extended", "Google", "control"),
    ("Applebot-Extended", "Apple", "control"),
    ("CCBot", "Common Crawl", "training"),
    ("Bytespider", "ByteDance", "training"),
    ("meta-externalagent", "Meta", "training"),
    ("Amazonbot", "Amazon", "training"),
]
SEARCH_AGENTS = ["Googlebot", "Bingbot"]


@dataclass
class Group:
    agents: list = field(default_factory=list)
    rules: list = field(default_factory=list)  # (allow: bool, pattern: str)


@dataclass
class Robots:
    groups: list = field(default_factory=list)
    sitemaps: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    def group_for(self, agent: str) -> list:
        token = agent.lower()
        specific = [g for g in self.groups if any(a != "*" and a in token for a in g.agents)]
        if specific:
            longest = max(len(a) for g in specific for a in g.agents if a in token)
            chosen = [g for g in specific if any(a in token and len(a) == longest for a in g.agents)]
        else:
            chosen = [g for g in self.groups if "*" in g.agents]
        return [r for g in chosen for r in g.rules]

    def allowed(self, agent: str, url_or_path: str) -> bool:
        parts = urlsplit(url_or_path)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        if path == "/robots.txt":
            return True
        best_len, verdict = -1, True
        for allow, pattern in self.group_for(agent):
            if pattern and _match(pattern, path):
                length = len(pattern)
                if length > best_len or (length == best_len and allow):
                    best_len, verdict = length, allow
        return verdict


def _normalise(path: str) -> str:
    return quote(unquote(path), safe="/?=&*$%:@!,;+~-._")


def _match(pattern: str, path: str) -> bool:
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = "".join(".*" if c == "*" else re.escape(c) for c in _normalise(body))
    return re.match(regex + ("$" if anchored else ""), _normalise(path)) is not None


def parse(text: str) -> Robots:
    robots = Robots()
    current: Group | None = None
    last_was_agent = False
    for n, raw in enumerate((text or "").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            robots.errors.append(f"line {n}: no ':' in '{raw.strip()[:60]}'")
            continue
        key, value = (s.strip() for s in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if current is None or not last_was_agent:
                current = Group()
                robots.groups.append(current)
            current.agents.append(value.lower())
            last_was_agent = True
            continue
        last_was_agent = False
        if key in ("allow", "disallow"):
            if current is None:
                robots.errors.append(f"line {n}: {key} before any user-agent")
                continue
            if key == "disallow" and value == "":
                continue  # "Disallow:" with no path allows everything
            current.rules.append((key == "allow", value))
        elif key == "sitemap":
            robots.sitemaps.append(value)
        elif key not in ("crawl-delay", "host", "content-signal", "clean-param", "request-rate"):
            robots.errors.append(f"line {n}: unknown directive '{key}'")
    return robots


def ai_policy(robots: Robots, path: str = "/") -> list[dict]:
    return [{"agent": a, "company": c, "purpose": p, "allowed": robots.allowed(a, path)}
            for a, c, p in AI_AGENTS]
