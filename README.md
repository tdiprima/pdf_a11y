# ♿📄 pdf-a11y

Got a pile of PDFs with accessibility problems?

Even worse... the original Word or InDesign files are **gone forever?** 💀

That's what **pdf-a11y** is for.

It batch-fixes accessibility problems that can be safely repaired using **only the PDF itself**.

It will:

* 🔧 Fix problems it can determine automatically
* 🌳 Build a best-guess accessibility structure/tag tree
* 🔍 Tell you what it **couldn't** safely figure out
* 🧑‍🔧 Flag PDFs that still need human attention

In other words:

**Computer fixes the obvious stuff. Human handles the weird stuff.**


# 🚀 How to Use It

First, go into the project directory:

```sh
cd pdf_a11y
```

Then it's basically:

**Audit → Fix → Verify → Handle leftovers**


## 1️⃣ Audit Your PDFs 🔍

Put your PDFs somewhere and run:

```sh
python3 main.py /path/to/your/pdfs --recursive --audit-only
```

Then open:

```text
reports/audit.csv
```

### 🚨 Look for this:

```text
no_text_layer
```

If a PDF says `no_text_layer`, it needs **OCR first**.

Why?

Because the PDF doesn't have usable text underneath the page image.

Basically:

👀 Human sees words.
🤖 Computer sees picture.

OCR needs to turn that picture into actual readable text before this tool can do its thing.


## 2️⃣ Fix the PDFs 🔧

Once they're ready:

```sh
python3 main.py /path/to/your/pdfs --recursive --out-dir /path/to/fixed
```

The repaired PDFs will be written to the directory you specify with:

```text
--out-dir
```

So your originals can stay put while the fixed versions go somewhere else. ✨


## 3️⃣ Check the Results 🧪

Now verify the repaired PDFs with **veraPDF**:

```sh
verapdf --flavour ua1 --format text /path/to/fixed/*.pdf
```

We're looking for the magic word:

```text
PASS ✅
```

If you get:

```text
FAIL ❌
```

that PDF still needs attention.

Don't assume the tool can safely fix everything automatically — some accessibility decisions require an actual human brain. 🧠


## 4️⃣ Check the Manual Work Report 👷

Finally, open:

```text
reports/remediation.csv
```

Look at the:

```text
manual_work
```

column.

Anything listed there is basically the tool saying:

🤖 "Boss, I got as far as I safely could. This one's yours."

Those are the PDFs that still need manual work.


# 🧠 The Whole Process

```text
        📚 PDFs
           │
           ▼
      🔍 AUDIT
           │
           ├── no_text_layer? ──► 👁️ OCR FIRST
           │
           ▼
       🔧 FIX
           │
           ▼
     🧪 veraPDF
           │
       ┌───┴───┐
       ▼       ▼
    PASS ✅   FAIL ❌
               │
               ▼
          🧑 Human Work
```

Audit and look for `no_text_layer`, run the remediation, verify with veraPDF, then check `manual_work` for anything requiring you.

<br>
