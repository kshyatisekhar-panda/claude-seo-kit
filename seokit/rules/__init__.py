"""Audit rules, one module per area.

Page rules take (page, response, add) where page is the extract() dict and
add(finding) records a finding for that page. Site rules take (site, add)
where site is the dict audit.py builds from the whole crawl.
"""

from . import ai, content, local, performance, schema, technical

PAGE_RULES = [technical.page_rules, content.page_rules, schema.page_rules, ai.page_rules]
SITE_RULES = [technical.site_rules, content.site_rules, schema.site_rules, ai.site_rules,
              local.site_rules, performance.site_rules]
