# Getting Started with XLSForm Architect

A plain-language guide. **No coding knowledge needed.**

XLSForm Architect turns a questionnaire (a Word, Excel, PDF, or text file) into
a ready-to-use survey form for **KoboToolbox, SurveyCTO, ODK, Ona, or
CommCare** — plus a set
of supporting documents. It runs on your own computer and does **not** use any
paid or online AI service.

This guide has two parts:

- **Part 1 — One-time setup.** Do this once on the computer that will run the
  tool. If you're not comfortable with it, hand this page to whoever set up
  your computer; it takes about 10 minutes.
- **Part 2 — Everyday use.** Simple, repeatable steps for anyone.

---

## Part 1 — One-time setup

You only do this **once** per computer.

### Step 1: Install Python

Python is the free engine the tool runs on.

- **Windows:** Go to <https://www.python.org/downloads/>, click the big
  **Download Python** button, run the installer, and — this part matters —
  **tick the box that says "Add Python to PATH"** before clicking Install.
- **Mac:** Same website, download and run the installer.

### Step 2: Get the tool onto the computer

Put the project folder (the one containing the `xlsform_architect` folder and
the `README.md` file) somewhere easy to find, for example your Desktop.

### Step 3: Open a command window in that folder

- **Windows:** Open the project folder, click the address bar at the top,
  type `cmd`, and press Enter. A black window opens.
- **Mac:** Open the **Terminal** app, type `cd ` (with a space), drag the
  project folder onto the window, and press Enter.

### Step 4: Install the tool's parts

In that window, type this line and press Enter:

```
pip install -r requirements.txt
```

Wait for it to finish (a minute or two, lots of text scrolls by — that's
normal).

### Step 5: Start the app

Type this and press Enter:

```
python run_ui.py
```

Your web browser opens automatically to the XLSForm Architect app. **That's
it — setup is done.**

> **Tip for later:** to start the app again another day, you only need to
> repeat **Step 3** and **Step 5** (open the command window in the folder, then
> run `python run_ui.py`). Setup Steps 1, 2 and 4 never need repeating.

### Optional: a one-click launcher (Windows)

So you don't have to type anything next time, create a shortcut:

1. In the project folder, right-click → **New → Text Document**.
2. Paste these two lines into it:

   ```
   cd /d "%~dp0"
   python run_ui.py
   ```
3. Save it, then rename the file to **`Start XLSForm Architect.bat`**
   (make sure it ends in `.bat`, not `.txt`).

From now on, just **double-click that file** to launch the app.

---

## Part 2 — Everyday use

Once the app is open in your browser:

1. **Upload your questionnaire.** Use the box on the left. It accepts Word
   (`.docx`), Excel (`.xlsx`), PDF, CSV, plain text (`.txt`), or a prepared
   JSON file.
2. **Choose where the form is going** — KoboToolbox, SurveyCTO, ODK, Ona,
   or CommCare.
   This matters: the tool checks your form against **that platform's own
   rules** and writes the file in its expected format (SurveyCTO, for
   example, uses slightly different column names — handled for you). The
   result screen also includes a **platform guide** tab with tips for the
   platform you chose.
3. *(Optional)* Type a **form title** and version.
4. Click **⚙️ Generate XLSForm.**
5. Watch the progress ticks, then **download** your results:
   - the **XLSForm** (`.xlsx`) — the file you upload to Kobo/SurveyCTO/ODK, or
   - the **full package** (`.zip`) — the form plus all the supporting documents.

That's the whole workflow. Repeat for each questionnaire.

---

## What you get back

| File | What it's for |
| --- | --- |
| **The XLSForm (`.xlsx`)** | The actual survey form — upload this to your platform. |
| **Data dictionary** | A plain list of every question, its type, and its answer options. |
| **QA report (PDF)** | A quality check confirming the form is valid and lists any issues. |
| **Assumption log** | Every automatic decision the tool made, so you can double-check it. |
| **Logic map** | A summary of the skip logic, validation rules, and calculations. |
| **Version history** | A running record of every form you've generated. |

---

## Writing a questionnaire the tool understands best

The tool is smart about plain questionnaires, but you'll get the cleanest
results if your document follows a few simple habits:

- **End questions with a question mark** — `What is your age?`
- **List answer options on their own lines**, right under the question:
  ```
  What is your gender?
  Male
  Female
  ```
- **Write skip rules in plain English** right after the question they apply
  to — `If yes, ask for the date.` Richer rules work too: `If age between
  18 and 65`, `Unless married`, `If question 4 is married`.
- **Number your questions** (`1.`, `Q2:`, `3)`) — then skip rules can refer
  to questions by number, which is the most reliable way to write them.
- **Answer codes are kept** — writing options as `1 = Single` stores the
  code `1` in your data with the label "Single".
- **Mark required questions** with a trailing `*` or `(required)`.
- **Use headings for sections** — a line in CAPITALS, or starting with
  "Section", becomes a group in the form.

You don't have to be perfect — the tool fills in the rest and tells you every
assumption it made in the assumption log.

---

## If something goes wrong

- **"python is not recognized" (Windows).** Python wasn't added to PATH during
  install. Re-run the Python installer, choose **Modify**, and make sure
  "Add Python to PATH" is ticked.
- **The browser didn't open.** Look in the command window for a line like
  `Local URL: http://localhost:8501` and paste that address into your browser.
- **A question came out as the wrong type** (e.g. a number treated as text).
  Open the **assumption log** to see why, then reword the question in your
  source document (for example, include the word "number" or "date") and
  generate again.
- **To stop the app**, close the browser tab and press **Ctrl + C** in the
  command window.

---

## Optional: AI assist

By default, everything described above happens entirely on your own
computer — nothing is sent anywhere. There is also an **optional** AI
add-on that can help with a few things a plain checklist-style tool can't
do:

- **Translate** your form's questions into other languages. If you've
  already written some translations yourself, those are always kept —
  AI only fills in the ones you didn't get to.
- **Untangle tricky skip instructions** — e.g. "if no, skip to question 20" —
  into the proper format automatically.
- **Suggest rules that compare two questions** — e.g. "the end date must be
  after the start date" — something a simple checklist can't figure out on
  its own since it only ever looks at one question at a time.
- **Suggest a better answer type** for a question that was hard to classify.
- **Give the finished form a second read-through** for anything that looks
  off, including confusing question names, in plain English.
- **Explain any issues found** in a sentence or two, so you don't need to
  guess what a technical validation message means.

This is completely optional and **off unless you turn it on**. To use it:

1. Get a DeepSeek API key (a paid service, separate from this tool) at
   [platform.deepseek.com](https://platform.deepseek.com).
2. In the app, open **"4 · 🤖 AI assist"** in the sidebar, paste your key,
   tick **Enable AI assist**, and pick what you want it to help with.
3. Anything AI suggests is clearly labelled and never applied blindly — it's
   always shown to you to review before you deploy the form.

If you never set this up, you'll never see a cost, and nothing about your
questionnaire ever leaves your computer.

---

## A note on privacy

By default, everything happens on your own computer — your questionnaires and
data are never sent anywhere. The one exception is the **optional AI assist**
feature above: if (and only if) you turn it on and supply an API key,
question labels are sent to DeepSeek's service to power that specific
feature. Nothing else in the tool ever makes a network connection.

---

Need more detail or the command-line version? See the main
[`README.md`](../README.md).
