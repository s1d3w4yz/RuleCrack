# Rule Chain Lab

A single-page tool for learning how password mask rules work: build an
ordered chain of transformation steps (capitalize, substitute, append,
prepend...), watch each step apply one at a time, and see how reordering
the chain changes the result. Export the chain as a Hashcat rule, and
batch-test it against a list of words.

## What it does

- Build a **step chain**: capitalize first letter, uppercase/lowercase
  everything, substitute a letter, append text, or prepend text. Steps run
  top to bottom — reorder them with the arrow buttons and watch the output
  change, to build intuition for why rule order matters.
- **Step-by-step trace**: see the word after each individual step, with
  the part that changed highlighted.
- **Hashcat rule export**: the same chain is rendered as a standard
  Hashcat rule line (e.g. `c sa4 se3 si1 so0 ss5 $! $1`), ready to drop
  into a `.rule` file.
- **Batch test**: run the whole chain against a list of words (one per
  line) to see how it generalizes beyond a single example.

## Usage

Open `index.html` directly in a browser, or serve the directory statically:

```sh
python3 -m http.server 8000
```

Then visit `http://localhost:8000/`.

No build step, no dependencies — it's a single self-contained HTML file.
