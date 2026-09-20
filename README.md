# Saccade

**A kinder way to read PDFs on Linux.**

Some of us lose the line halfway through a paragraph. Some of us read the same
sentence three times and still take nothing in. Saccade is a PDF reader built
around that.

It uses **bionic reading**: the first few letters of every word are bolded, so
your eye lands on a fixation point instead of hunting for one, and the rest of
the word is filled in almost without effort. How much gets bolded is up to you,
and it switches off with one key if you would rather compare. On top of that you
can set the spacing and size that actually suit you, and dim everything except
the paragraph you are on.

It is named after *saccades* — the small, quick jumps your eyes make as you
read.

**Maths gets particular care.** Copying a formula out of a PDF usually gives you
nonsense, because a PDF stores placed glyphs rather than equations. Saccade
instead shows each formula exactly as the book prints it — fraction bars, roots,
limits and big operators intact — in the colours of whatever theme you are
reading in.

> Saccade is in beta (0.9). If something reads badly, please tell me in
> [Issues](https://github.com/khodekia/saccade/issues) — a screenshot and the
> book's name is plenty.

## What it does

**Makes the words easier to take in**

- Bionic fixations: bolds the first part of every word, and you decide how much
  (20–80%), or turn it off with `Ctrl+B`
- **Focus mode** (`F2`) dims every paragraph except the one you are reading; it
  follows your pointer, so there is nothing to learn
- **Easy-reading setup** — one menu item, and the text gets bigger, the line
  shorter, the spacing wider and the page warmer. `Reset reading settings` puts
  everything back, so it is safe to experiment
- Line, letter and word spacing, and column width, all adjustable. Wider letter
  spacing is one of the few things with real evidence behind it for dyslexic
  readers
- Fonts made for easier reading — OpenDyslexic, Atkinson Hyperlegible, Lexend —
  appear at the top of the font list when you have them installed
  (**Help → Reading fonts** shows how to get them)
- Five colour themes, from warm paper to night, plus a zen mode (`F11`) that
  hides everything but the words

**Keeps your book a book**

- Text re-flows into a comfortable column, but headings stay headings, bold
  stays bold, and footnote markers stay where they belong
- **Formulas are shown as the book prints them** — fractions with their bars,
  roots, limits, big operators — instead of the scrambled text you get from
  copying maths out of a PDF
- **Scanned books** are shown as the scanned page, because their hidden OCR text
  turns `k ∈ ℤ₊` into `k E Z+`
- The contents pages inside a book are clickable, and so is the chapter list in
  the sidebar
- Bookmarks, full-book search, and it remembers the page you stopped on

## Getting it

### Download and run

No terminal, no Python, no coding. Go to the
[Releases page](https://github.com/khodekia/saccade/releases) and download
the file for your system:

- **Debian, Ubuntu, Linux Mint and similar** — download the `.deb` file and
  double-click it to install. If your file manager does not offer to install
  it, open a terminal in the download folder and run:
  ```bash
  sudo apt install ./saccade_*_all.deb
  ```
- **Any other Linux distro** — download the `.AppImage` file, right-click it
  and tick "Allow executing as program" (or run `chmod +x Saccade-*.AppImage`
  in a terminal), then double-click it to run. It carries its own Qt and
  PyMuPDF, so there is nothing else to install.
- **Arch Linux** — see the AUR instructions below.

### Arch Linux (AUR)

Once it is on the AUR, any helper will do:

```bash
yay -S saccade
```

Or build it yourself from this repository:

```bash
cd packaging/aur
makepkg -si
```

> **Before uploading to the AUR:** tag a `v0.9.1` release, put the release
> tarball's real checksum in `sha256sums` (`makepkg -g` prints it), then
> regenerate `.SRCINFO` with `makepkg --printsrcinfo > .SRCINFO`.

### Building from source

For developers: you need Linux, Python 3.9 or newer, PyQt6 and PyMuPDF. The
last two install themselves with the app.

```bash
git clone https://github.com/khodekia/saccade.git
cd saccade
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/saccade
```

While hacking on it, run it straight from the checkout instead:

```bash
.venv/bin/python -m saccade
```

### Building the .deb or AppImage yourself

```bash
bash packaging/build_deb.sh
sudo apt install ./packaging/dist/saccade_*_all.deb
```

```bash
bash packaging/build_appimage.sh
./packaging/dist/Saccade-<version>-x86_64.AppImage
```

The AppImage build downloads `appimagetool` once.

## Using it

1. Drop a PDF onto the window, or press `Ctrl+O`.
2. Drag the slider to taste; `Ctrl+B` turns the bolding off and on so you can
   compare.
3. `N` and `B` turn pages (`PgDown`/`PgUp` work too). `Space` scrolls and moves
   on at the end of a page. Type a page number in the toolbar to jump.
4. `Ctrl+F` searches the whole book; hits appear in the **Results** tab.
5. `Ctrl+D` bookmarks the page you are on.
6. The **View** menu holds the easy-reading setup, focus mode, themes, sizes and
   spacing.

`F1` lists every shortcut.

If a book opens as a wall of nonsense, it is probably a scan — run OCR on it
first (`ocrmypdf in.pdf out.pdf`) and it will behave.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests -t .
.venv/bin/python tools/smoke_gui.py     # drives the real window, headless
```

## How it is put together

```
saccade/
  bionic.py      # the fixation algorithm: word -> HTML with bold openings
  document.py    # PDF backends, text extraction, outline, formula crops
  layout.py      # page rendering: structured flow, formulas, page-layout mode
  settings.py    # everything that is remembered between sessions
  support.py     # donation wallets, repo link, bundled icons
  theme.py       # reading themes and the application's own styling
  app.py         # start-up and the command line
  ui/
    main_window.py  # window, toolbar, menus, shortcuts
    reader_view.py  # the reading surface itself
    about_dialog.py # this app's About box
    sidebar.py      # chapters, bookmarks, search results
    search.py       # full-book search, off the main thread
packaging/       # .deb, AppImage and AUR recipes
tools/           # headless checks that drive the real window
tests/           # unit tests for the algorithm, the PDF layer and search
```

## Thank you

If Saccade makes your reading easier and you feel like buying me a coffee:

**Bitcoin (BTC)** — *BTC network*
```
bc1q0m62svyqcl9n898yvccza4dx049c3uuqqg28zj
```

**Ethereum (ETH)** — *ETH network*
```
0x1808eA06242729efA2E5a7B9c212530169011392
```

**USDC** — *Ethereum network*
```
0x1808eA06242729efA2E5a7B9c212530169011392
```

**Dogecoin (DOGE)** — *Doge network*
```
DGfQtSnAgqBXzeuyQSmKLeMgaiVT5Rt1pT
```

**Toncoin** — *TON network*
```
UQDTgx7WQZHOc8IAkhuIn2srrJj0XjOLT8Ej1nssfAhyKtq9
```

No pressure at all — the app is free either way, and always will be.

## Licence

MIT, see [LICENSE](LICENSE). The bionic-reading idea was popularised by Renato
Casutt.
