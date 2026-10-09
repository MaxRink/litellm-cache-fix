from pathlib import Path
p = Path('/app/.venv/lib/python3.13/site-packages/litellm/integrations/opentelemetry.py')
s = p.read_text()
team = '''        # Stamp team attributes onto the SERVER (root) span before it is
        # closed, so the trace root carries them like every child span.
        self._set_team_attributes_on_proxy_span_from_kwargs(kwargs)

'''
if s.count(team) != 1: raise SystemExit(f'expected one team block, found {s.count(team)}')
team_at = s.index(team)
close_at = s.index('        if (\n', s.index('        # 6. Do NOT end parent span'))
if team_at <= close_at: raise SystemExit('unexpected method layout')
s = s[:team_at] + s[team_at + len(team):]
close_at = s.index('        if (\n', s.index('        # 6. Do NOT end parent span'))
s = s[:close_at] + team + s[close_at:]
if s.count(team) != 1: raise SystemExit('team insertion failed')
p.write_text(s)
