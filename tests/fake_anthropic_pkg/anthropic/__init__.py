"""Stand-in for the anthropic SDK so the report path can be tested offline. LAST holds the last request."""
LAST = None
class _B:
    def __init__(s,t): s.type="text"; s.text=t
class _U: input_tokens=12345; output_tokens=2345
class _M:
    def __init__(s,t): s.content=[_B(t)]; s.usage=_U()
REPORT='''# Kick-off: Example Co. order dashboard

3 Mar 2026 · 31:05 · Sam (presenter), Alex

## Summary
Sam walks Alex through the order dashboard project.

## TL;DR
- **orders_daily** is the main table.

## System diagram
```mermaid
flowchart LR
  A["Web shop"] --> B["Warehouse DB"] --> C["Dashboard"]
```
Read left to right.

## Action items
### Alex
- [ ] Draft the first chart (12:40)
### Sam
- [x] Share the sample data (29:55)

## Requirements & details
| Requirement | Detail |
| --- | --- |
| Colours | green, yellow, red |

## Walkthrough
### 05:10-09:05 · Dashboard overview
Shown in the browser.
![Dashboard overview (16:15)](frames/f023_00-16-15.jpg)

## Glossary
| Term | Meaning |
| --- | --- |
| KPI | Key performance indicator |

## Open questions
- [ ] Which date range?
'''
class _S:
    def __init__(s,**k): s.k=k; global LAST; LAST=k
    def __enter__(s): return s
    def __exit__(s,*a): pass
    @property
    def text_stream(s):
        for i in range(0,len(REPORT),500): yield REPORT[i:i+500]
    def get_final_message(s): return _M(REPORT)
class _Msgs:
    def stream(s,**k): return _S(**k)
class Anthropic:
    def __init__(s,api_key): assert api_key; s.messages=_Msgs()
