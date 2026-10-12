# FRAMES snapshot builder fixtures

Real rendered article HTML from English Wikipedia, as the MediaWiki parse API returns it
(`action=parse&oldid=<revision>&prop=text&disableeditsection=1&disablelimitreport=1`), so the
builder's text conversion is tested on what it will really read. The repo's commit hooks strip
trailing whitespace from these files; the builder collapses whitespace, so its output is the same.

| File | Article | Revision |
| -- | -- | -- |
| `harriet_lane_1234251973.html` | [Harriet Lane](https://en.wikipedia.org/w/index.php?oldid=1234251973) | 1234251973 (2024-07-13) |
| `list_of_mayors_of_utica_1220067810.html` | [List of mayors of Utica, New York](https://en.wikipedia.org/w/index.php?oldid=1220067810) | 1220067810 (2024-04-21) |

Text by Wikipedia contributors, licensed under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); the revision links above
carry the full attribution history.
