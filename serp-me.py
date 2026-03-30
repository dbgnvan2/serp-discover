import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import subprocess
import sys
import threading
import os
import json
import re
import time
from datetime import datetime
import yaml

from apply_domain_override_candidates import merge_overrides, write_overrides
from classifiers import ENTITY_TYPE_DESCRIPTIONS, ENTITY_TYPES, EntityClassifier
from generate_domain_override_candidates import (
    collect_candidates,
    load_json,
    load_overrides,
    split_candidates,
)
from refresh_analysis_outputs import load_config_paths, refresh_analysis_outputs


def normalize_keyword_list(keywords):
    return [value.strip().lower() for value in keywords if str(value).strip()]


def derive_topic_slug_from_keyword_file(keyword_file):
    """Return a normalized lowercase slug from the keyword CSV filename.

    Examples:
        keywords.csv                  -> keywords
        keywords_estrangement.csv     -> estrangement
        Substance_Use.csv             -> substance_use
        Basic Series Tape 7.csv       -> basic_series_tape_7
    """
    stem = os.path.splitext(os.path.basename(keyword_file))[0]
    if stem.lower().startswith("keywords_"):
        stem = stem[len("keywords_"):]
    return stem.lower().replace(" ", "_")


class SerpLauncherApp:
    EXIT_STATUS_LABELS = {
        0: "SUCCESS",
        1: "MISMATCH",
        2: "ERROR",
    }
    DOMAIN_REVIEW_TAG_STYLES = {
        "counselling": {"background": "#e8f5e9"},
        "legal": {"background": "#fff3e0"},
        "directory": {"background": "#e3f2fd"},
        "nonprofit": {"background": "#f3e5f5"},
        "government": {"background": "#eceff1"},
        "media": {"background": "#fff8e1"},
        "professional_association": {"background": "#e0f7fa"},
        "education": {"background": "#f1f8e9"},
        "unknown": {"background": "#f5f5f5"},
    }
    REPORT_MODEL_OPTIONS = [
        "claude-opus-4-6",
        "claude-sonnet-4-20250514",
        "claude-opus-4-1-20250805",
        "claude-opus-4-20250514",
        "claude-3-7-sonnet-20250219",
    ]
    MAIN_REPORT_DEFAULT_MODEL = "claude-opus-4-6"
    ADVISORY_DEFAULT_MODEL = "claude-sonnet-4-20250514"

    def __init__(self, root):
        self.root = root
        self.root.title("SERP Intelligence Launcher")
        self.root.geometry("800x650")
        self.domain_review_window = None
        self.domain_review_rows = []
        self.domain_review_selected_row = None
        self.inline_type_editor = None
        self.last_completed_script = None
        self.keyword_file_options = {}
        self.current_run_context = None

        # Styles
        style = ttk.Style()
        style.configure("TButton", padding=6)
        style.configure("TLabel", font=("Helvetica", 10))
        style.configure("Header.TLabel", font=("Helvetica", 16, "bold"))

        # Header
        header_frame = ttk.Frame(root)
        header_frame.pack(pady=15, fill="x", padx=20)

        title_label = ttk.Label(
            header_frame, text="SERP Intelligence Tool", style="Header.TLabel")
        title_label.pack()

        subtitle_label = ttk.Label(
            header_frame, text="Bridge Strategy & Market Analysis Pipeline")
        subtitle_label.pack()

        # Main Content Area (Split into Selection and Description)
        content_frame = ttk.Frame(root)
        content_frame.pack(pady=10, fill="both", expand=True, padx=20)

        # Left Side: List of Scripts
        list_frame = ttk.LabelFrame(content_frame, text="Available Scripts")
        list_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

        self.script_listbox = tk.Listbox(
            list_frame, height=10, font=("Courier", 12), activestyle="none")
        self.script_listbox.pack(
            side="left", fill="both", expand=True, padx=5, pady=5)
        self.script_listbox.bind('<<ListboxSelect>>', self.on_select)

        scrollbar = ttk.Scrollbar(
            list_frame, orient="vertical", command=self.script_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.script_listbox.config(yscrollcommand=scrollbar.set)

        # Right Side: Description & Context
        desc_frame = ttk.LabelFrame(content_frame, text="Context & Usage")
        desc_frame.pack(side="right", fill="both", expand=True)

        self.desc_text = tk.Text(desc_frame, wrap="word", height=10,
                                 width=35, bg="#f9f9f9", state="disabled", font=("Helvetica", 11))
        self.desc_text.pack(fill="both", expand=True, padx=10, pady=10)

        # Actions Configuration
        self.scripts = [
            {
                "label": "1. Run Full Pipeline (Daily)",
                "file": "run_pipeline.py",
                "args": [],
                "desc": (
                    "WHEN: Run this once per day or weekly.\n\n"
                    "WHY: This is the 'Daily Driver'. It performs the full audit:\n"
                    "  - Fetches SERP data (Google, Maps, AI)\n"
                    "  - Optional: runs AI-likely query alternatives A.1 and A.2\n"
                    "  - Enriches data (HTML parsing, Entity Classification)\n"
                    "  - Stores history in SQLite\n"
                    "  - Generates Excel/Markdown reports\n"
                    "  - Validates data integrity"
                )
            },
            {
                "label": "2. List Content Opportunities",
                "file": "generate_content_brief.py",
                "args": [],
                "desc": (
                    "WHEN: Run when you are ready to write content.\n\n"
                    "WHY: The 'Strategist'. Generates a prompt-informed content opportunity report from the latest pipeline data.\n\n"
                    "OUTPUT: Writes topic-matched content opportunities and advisory briefing files and prints a concise summary in the log.\n\n"
                    "NOTE: Requires Anthropic API access (ANTHROPIC_API_KEY). If unavailable, this step fails."
                )
            },
            {
                "label": "3. List Volatility Keywords",
                "file": "visualize_volatility.py",
                "args": ["--list"],
                "desc": (
                    "WHEN: Run after accumulating a few days of data.\n\n"
                    "WHY: The 'Analyst'. Lists keywords available for historical tracking.\n\n"
                    "NOTE: To generate a chart, run from command line: python visualize_volatility.py --keyword 'Your Keyword'"
                )
            },
            {
                "label": "4. Export History to CSV",
                "file": "export_history.py",
                "args": [],
                "desc": (
                    "WHEN: Run monthly or when external analysis is needed.\n\n"
                    "WHY: Dumps the entire SQLite database (runs, serp_results, features) into CSV files in the 'exports/' folder."
                )
            },
            {
                "label": "5. Verify Database",
                "file": "verify_enrichment.py",
                "args": [],
                "desc": (
                    "WHEN: Run if you suspect data issues.\n\n"
                    "WHY: Checks the SQLite database to confirm that enrichment data (URL features, Domain features) is being correctly populated."
                )
            },
            {
                "label": "6. Review Domain Override Candidates",
                "file": None,
                "args": [],
                "action": "review_domain_overrides",
                "desc": (
                    "WHEN: Run after a pipeline run when you want to improve entity classification.\n\n"
                    "WHY: Opens an in-app checklist of recurring domains not yet in domain_overrides.yml.\n\n"
                    "OUTPUT: Lets you approve checked items directly into domain_overrides.yml."
                )
            },
            {
                "label": "7. Run Feasibility Analysis (Moz DA)",
                "file": "run_feasibility.py",
                "args": [],
                "desc": (
                    "WHEN: Run after a pipeline run, or any time you want to check DA competitiveness.\n\n"
                    "WHY: Uses the Moz API to score each keyword by Domain Authority gap. "
                    "Generates a standalone feasibility report with:\n"
                    "  - High / Moderate / Low Feasibility per keyword\n"
                    "  - Hyper-local pivot suggestions for Low Feasibility keywords\n"
                    "  - Local 3-pack check for pivot variants (optional)\n\n"
                    "NOTE: Requires MOZ_TOKEN in .env (free Moz tier: 50 rows/month). "
                    "Results are cached for 30 days so repeat runs don't burn quota.\n\n"
                    "OUTPUT: Writes feasibility_{topic}_{timestamp}.md"
                )
            },
        ]

        for s in self.scripts:
            self.script_listbox.insert(tk.END, s["label"])

        # Control Buttons
        btn_frame = ttk.Frame(root)
        btn_frame.pack(pady=10, fill="x", padx=20)

        self.ai_query_alts_var = tk.BooleanVar(value=False)
        self.ai_query_alts_chk = ttk.Checkbutton(
            btn_frame,
            text="Run 2 AI-likely alternatives (A.1, A.2)",
            variable=self.ai_query_alts_var
        )
        self.ai_query_alts_chk.pack(side="left", padx=5)

        self.low_api_mode_var = tk.BooleanVar(value=False)
        self.low_api_mode_chk = ttk.Checkbutton(
            btn_frame,
            text="Low API Mode",
            variable=self.low_api_mode_var,
            command=self.on_low_api_mode_toggle
        )
        self.low_api_mode_chk.pack(side="left", padx=5)

        self.balanced_mode_var = tk.BooleanVar(value=True)
        self.balanced_mode_chk = ttk.Checkbutton(
            btn_frame,
            text="Balanced Mode",
            variable=self.balanced_mode_var,
        )
        self.balanced_mode_chk.pack(side="left", padx=5)

        self.deep_research_mode_var = tk.BooleanVar(value=False)
        self.deep_research_mode_chk = ttk.Checkbutton(
            btn_frame,
            text="Deep Research Mode",
            variable=self.deep_research_mode_var,
        )
        self.deep_research_mode_chk.pack(side="left", padx=5)

        model_frame = ttk.Frame(root)
        model_frame.pack(fill="x", padx=20, pady=(0, 6))
        ttk.Label(model_frame, text="Main Report Model:").pack(side="left", padx=(0, 6))
        self.main_model_var = tk.StringVar(value=self.MAIN_REPORT_DEFAULT_MODEL)
        self.main_model_combo = ttk.Combobox(
            model_frame,
            textvariable=self.main_model_var,
            values=self.REPORT_MODEL_OPTIONS,
            width=28,
        )
        self.main_model_combo.pack(side="left", padx=(0, 12))

        ttk.Label(model_frame, text="Advisory Model:").pack(side="left", padx=(0, 6))
        self.advisory_model_var = tk.StringVar(value=self.ADVISORY_DEFAULT_MODEL)
        self.advisory_model_combo = ttk.Combobox(
            model_frame,
            textvariable=self.advisory_model_var,
            values=self.REPORT_MODEL_OPTIONS,
            width=28,
        )
        self.advisory_model_combo.pack(side="left")

        keyword_file_frame = ttk.Frame(root)
        keyword_file_frame.pack(fill="x", padx=20, pady=(0, 4))
        ttk.Label(keyword_file_frame, text="Keyword File:").pack(side="left", padx=(0, 6))
        self.keyword_file_var = tk.StringVar(value="")
        self.keyword_file_combo = ttk.Combobox(
            keyword_file_frame,
            textvariable=self.keyword_file_var,
            state="readonly",
            width=50,
        )
        self.keyword_file_combo.pack(side="left", fill="x", expand=True)
        ttk.Button(
            keyword_file_frame,
            text="Refresh Files",
            command=self.refresh_keyword_file_options,
        ).pack(side="left", padx=(6, 0))

        new_keywords_frame = ttk.Frame(root)
        new_keywords_frame.pack(fill="x", padx=20, pady=(0, 8))
        ttk.Label(
            new_keywords_frame,
            text="New Keywords (comma separated):"
        ).pack(side="left", padx=(0, 6))
        self.new_keywords_var = tk.StringVar(value="")
        self.new_keywords_entry = ttk.Entry(
            new_keywords_frame, textvariable=self.new_keywords_var, width=52
        )
        self.new_keywords_entry.pack(side="left", fill="x", expand=True)

        self.run_btn = ttk.Button(
            btn_frame, text="Run Selected Script", command=self.run_script, state="disabled")
        self.run_btn.pack(side="right", padx=5)

        ttk.Button(btn_frame, text="Clear Log",
                   command=self.clear_log).pack(side="right", padx=5)

        # Output Log
        log_frame = ttk.LabelFrame(root, text="Execution Log")
        log_frame.pack(pady=(0, 20), fill="both", expand=True, padx=20)

        self.log_text = scrolledtext.ScrolledText(
            log_frame, height=12, state="disabled", bg="#1e1e1e", fg="#00ff00", font=("Consolas", 10))
        self.log_text.pack(fill="both", expand=True, padx=5, pady=5)
        self.refresh_keyword_file_options()

    def on_select(self, event):
        selection = self.script_listbox.curselection()
        if selection:
            index = selection[0]
            desc = self.scripts[index]["desc"]
            self.update_desc(desc)
            self.run_btn.config(state="normal")
        else:
            self.update_desc("")
            self.run_btn.config(state="disabled")

    def update_desc(self, text):
        self.desc_text.config(state="normal")
        self.desc_text.delete("1.0", tk.END)
        self.desc_text.insert(tk.END, text)
        self.desc_text.config(state="disabled")

    def config_path(self):
        return os.path.join(os.getcwd(), "config.yml")

    def load_config(self):
        path = self.config_path()
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def save_config(self, config):
        with open(self.config_path(), "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, sort_keys=False, allow_unicode=False)

    def read_keyword_file(self, path):
        if not os.path.exists(path):
            return []
        keywords = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                value = line.strip()
                if not value:
                    continue
                if value.lower() == "keyword":
                    continue
                keywords.append(value)
        return keywords

    def write_keyword_file(self, path, keywords):
        with open(path, "w", encoding="utf-8") as f:
            for keyword in keywords:
                f.write(f"{keyword}\n")

    def parse_new_keywords(self, text):
        return [part.strip() for part in text.split(",") if part.strip()]

    def extract_priority_keywords_from_analysis(self, json_path):
        if not json_path or not os.path.exists(json_path):
            return []
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []
        priorities = data.get("strategic_flags", {}).get("content_priorities", [])
        allowed_actions = {"defend", "strengthen", "enter_cautiously"}
        return [
            item.get("keyword")
            for item in priorities
            if item.get("action") in allowed_actions and item.get("keyword")
        ]

    def sanitize_keyword_slug(self, keyword):
        slug = keyword.strip().lower().replace(" ", "_")
        slug = re.sub(r"[^a-z0-9_]", "", slug)
        slug = re.sub(r"_+", "_", slug).strip("_")
        return slug or "custom"

    def derive_topic_slug(self, keyword_file):
        return derive_topic_slug_from_keyword_file(keyword_file)

    def build_output_names(self, topic_slug):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        return {
            "output_xlsx": f"market_analysis_{topic_slug}_{timestamp}.xlsx",
            "output_json": f"market_analysis_{topic_slug}_{timestamp}.json",
            "output_md": f"market_analysis_{topic_slug}_{timestamp}.md",
            "report_out": f"content_opportunities_{topic_slug}_{timestamp}.md",
            "advisory_out": f"advisory_briefing_{topic_slug}_{timestamp}.md",
            "feasibility_out": f"feasibility_{topic_slug}_{timestamp}.md",
        }

    def find_latest_topic_output(self, prefix, topic_slug, extension):
        pattern = re.compile(
            rf"^{re.escape(prefix)}_{re.escape(topic_slug)}(?:_\d{{8}}_\d{{4}})?{re.escape(extension)}$"
        )
        matches = []
        cwd = os.getcwd()
        for name in os.listdir(cwd):
            if not pattern.match(name):
                continue
            path = os.path.join(cwd, name)
            if os.path.isfile(path):
                matches.append((os.path.getmtime(path), path))
        if not matches:
            return None
        matches.sort(key=lambda item: item[0], reverse=True)
        return matches[0][1]

    def find_latest_any_output(self, prefix, extension):
        pattern = re.compile(
            rf"^{re.escape(prefix)}_.+?(?:_\d{{8}}_\d{{4}})?{re.escape(extension)}$"
        )
        matches = []
        cwd = os.getcwd()
        for name in os.listdir(cwd):
            if not pattern.match(name):
                continue
            path = os.path.join(cwd, name)
            if os.path.isfile(path):
                matches.append((os.path.getmtime(path), path))
        if not matches:
            return None
        matches.sort(key=lambda item: item[0], reverse=True)
        return matches[0][1]

    def find_matching_topic_slug(self, keyword_file):
        target_keywords = normalize_keyword_list(self.read_keyword_file(keyword_file))
        if not target_keywords:
            return None
        cwd = os.getcwd()
        candidates = []
        for name in os.listdir(cwd):
            if not (name.startswith("keywords_") and name.endswith(".csv")):
                continue
            path = os.path.join(cwd, name)
            if not os.path.isfile(path) or os.path.abspath(path) == os.path.abspath(keyword_file):
                continue
            candidate_keywords = normalize_keyword_list(self.read_keyword_file(path))
            if candidate_keywords == target_keywords:
                candidates.append((os.path.getmtime(path), derive_topic_slug_from_keyword_file(path)))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    def resolve_existing_analysis_outputs(self, keyword_file, topic_slug):
        latest_json = self.find_latest_topic_output("market_analysis", topic_slug, ".json")
        latest_xlsx = self.find_latest_topic_output("market_analysis", topic_slug, ".xlsx")
        latest_md = self.find_latest_topic_output("market_analysis", topic_slug, ".md")

        if latest_json or latest_xlsx or latest_md:
            return topic_slug, latest_json, latest_xlsx, latest_md

        config = self.load_config()
        files_cfg = config.get("files", {}) if isinstance(config, dict) else {}
        configured_json = files_cfg.get("output_json")
        configured_xlsx = files_cfg.get("output_xlsx")
        configured_md = files_cfg.get("output_md")
        config_json_path = os.path.join(os.getcwd(), configured_json) if configured_json else None
        config_xlsx_path = os.path.join(os.getcwd(), configured_xlsx) if configured_xlsx else None
        config_md_path = os.path.join(os.getcwd(), configured_md) if configured_md else None

        if (
            os.path.basename(keyword_file) == "keywords.csv"
            and config_json_path and os.path.exists(config_json_path)
        ):
            inferred_slug = re.sub(r"(?:_\d{8}_\d{4})?\.json$", "", os.path.basename(config_json_path))
            inferred_slug = re.sub(r"^market_analysis_", "", inferred_slug)
            return (
                inferred_slug or topic_slug,
                config_json_path,
                config_xlsx_path if config_xlsx_path and os.path.exists(config_xlsx_path) else None,
                config_md_path if config_md_path and os.path.exists(config_md_path) else None,
            )

        matching_slug = self.find_matching_topic_slug(keyword_file)
        if matching_slug:
            return (
                matching_slug,
                self.find_latest_topic_output("market_analysis", matching_slug, ".json"),
                self.find_latest_topic_output("market_analysis", matching_slug, ".xlsx"),
                self.find_latest_topic_output("market_analysis", matching_slug, ".md"),
            )

        if os.path.basename(keyword_file) == "keywords.csv":
            return (
                topic_slug,
                self.find_latest_any_output("market_analysis", ".json"),
                self.find_latest_any_output("market_analysis", ".xlsx"),
                self.find_latest_any_output("market_analysis", ".md"),
            )

        return topic_slug, latest_json, latest_xlsx, latest_md

    def refresh_keyword_file_options(self):
        options = []
        cwd = os.getcwd()
        for name in os.listdir(cwd):
            if not (
                (name == "keywords.csv")
                or (name.startswith("keywords_") and name.endswith(".csv"))
            ):
                continue
            path = os.path.join(cwd, name)
            if not os.path.isfile(path):
                continue
            keywords = self.read_keyword_file(path)
            options.append({
                "display": f"{name} ({len(keywords)} keywords)",
                "path": path,
                "mtime": os.path.getmtime(path),
            })
        options.sort(key=lambda item: (-item["mtime"], item["display"]))
        self.keyword_file_options = {"<New / none>": None}
        values = ["<New / none>"]
        for item in options:
            self.keyword_file_options[item["display"]] = item["path"]
            values.append(item["display"])
        self.keyword_file_combo["values"] = values
        if self.keyword_file_var.get() not in self.keyword_file_options:
            self.keyword_file_var.set(values[0] if values else "")

    def prepare_keyword_run_context(self, script_file):
        selected_display = self.keyword_file_var.get().strip()
        selected_path = self.keyword_file_options.get(selected_display) if selected_display else None
        new_keywords = self.parse_new_keywords(self.new_keywords_var.get())

        if not selected_path and not new_keywords:
            raise ValueError("Please select an existing keyword file or enter new keywords.")

        added_keywords = []
        keyword_file = selected_path

        if selected_path and not new_keywords:
            keywords = self.read_keyword_file(selected_path)
        elif not selected_path and new_keywords:
            slug = self.sanitize_keyword_slug(new_keywords[0])
            keyword_file = os.path.join(os.getcwd(), f"keywords_{slug}.csv")
            keywords = new_keywords
            self.write_keyword_file(keyword_file, keywords)
        else:
            existing_keywords = self.read_keyword_file(selected_path)
            seen = {value.lower(): value for value in existing_keywords}
            keywords = list(existing_keywords)
            for keyword in new_keywords:
                lowered = keyword.lower()
                if lowered in seen:
                    continue
                seen[lowered] = keyword
                keywords.append(keyword)
                added_keywords.append(keyword)
            self.write_keyword_file(selected_path, keywords)

        topic_slug = self.derive_topic_slug(keyword_file)
        output_names = self.build_output_names(topic_slug)
        resolved_topic_slug, latest_json, latest_xlsx, latest_md = self.resolve_existing_analysis_outputs(
            keyword_file,
            topic_slug,
        )
        if resolved_topic_slug != topic_slug:
            topic_slug = resolved_topic_slug
            output_names = self.build_output_names(topic_slug)

        if script_file == "run_pipeline.py":
            config = self.load_config()
            files_cfg = config.setdefault("files", {})
            files_cfg["input_csv"] = os.path.basename(keyword_file)
            files_cfg["output_xlsx"] = output_names["output_xlsx"]
            files_cfg["output_json"] = output_names["output_json"]
            files_cfg["output_md"] = output_names["output_md"]
            self.save_config(config)
            input_json = os.path.join(os.getcwd(), output_names["output_json"])
        else:
            input_json = latest_json

        self.refresh_keyword_file_options()
        selected_base = os.path.basename(keyword_file)
        for display, path in self.keyword_file_options.items():
            if path and os.path.basename(path) == selected_base:
                self.keyword_file_var.set(display)
                break

        return {
            "keyword_file": keyword_file,
            "keywords": keywords,
            "added_keywords": added_keywords,
            "topic_slug": topic_slug,
            "output_names": output_names,
            "input_json": input_json,
            "latest_json": latest_json,
            "latest_xlsx": latest_xlsx,
            "latest_md": latest_md,
        }

    def run_script(self):
        selection = self.script_listbox.curselection()
        if not selection:
            return

        script_info = self.scripts[selection[0]]
        if script_info.get("action") == "review_domain_overrides":
            self.open_domain_override_review()
            return

        run_context = None
        output_names = None
        if script_info["file"] in {"run_pipeline.py", "generate_content_brief.py", "run_feasibility.py"}:
            try:
                run_context = self.prepare_keyword_run_context(script_info["file"])
            except ValueError as exc:
                messagebox.showerror("Keyword Setup", str(exc))
                return
            output_names = run_context["output_names"]
            if script_info["file"] == "generate_content_brief.py" and not run_context.get("input_json"):
                messagebox.showerror(
                    "Content Opportunities",
                    "No existing market analysis JSON was found for this topic. Run Full Pipeline first."
                )
                return
            if script_info["file"] == "run_feasibility.py" and not run_context.get("input_json"):
                messagebox.showerror(
                    "Feasibility Analysis",
                    "No existing market analysis JSON was found for this topic. Run Full Pipeline first."
                )
                return
        else:
            archived = []

        cmd = [sys.executable, script_info["file"]]
        if script_info["file"] == "generate_content_brief.py":
            main_model = self.main_model_var.get().strip() or self.MAIN_REPORT_DEFAULT_MODEL
            advisory_model = self.advisory_model_var.get().strip() or self.ADVISORY_DEFAULT_MODEL
            cmd.extend([
                "--json", run_context["input_json"],
                "--list",
                "--report-out", output_names["report_out"],
                "--advisory-briefing",
                "--advisory-out", output_names["advisory_out"],
                "--prompt-spec", os.path.join("prompts", "main_report"),
                "--llm-model", main_model,
                "--advisory-model", advisory_model,
                "--use-llm",
            ])
        elif script_info["file"] == "run_feasibility.py":
            feasibility_out = output_names.get("feasibility_out", "")
            cmd.extend(["--json", run_context["input_json"]])
            if feasibility_out:
                cmd.extend(["--out", feasibility_out])
        else:
            cmd.extend(script_info["args"])
        cwd = os.getcwd()
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"  # force line-by-line stdout flush into the log
        env["SERP_LOW_API_MODE"] = "1" if self.low_api_mode_var.get() else "0"
        env["SERP_ENABLE_AI_QUERY_ALTERNATIVES"] = (
            "0" if self.low_api_mode_var.get()
            else ("1" if self.ai_query_alts_var.get() else "0")
        )
        env["SERP_BALANCED_MODE"] = (
            "0" if self.low_api_mode_var.get()
            else ("1" if self.balanced_mode_var.get() else "0")
        )
        env["SERP_DEEP_RESEARCH_MODE"] = (
            "0" if self.low_api_mode_var.get()
            else ("1" if self.deep_research_mode_var.get() else "0")
        )
        env["SERP_SINGLE_KEYWORD"] = ""
        if run_context and output_names:
            previous_json = run_context.get("latest_json")
            priority_keywords = self.extract_priority_keywords_from_analysis(previous_json)
            env["SERP_AI_PRIORITY_KEYWORDS"] = "||".join(priority_keywords)
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.current_run_context = run_context

        self.log("\n" + "=" * 68 + "\n")
        self.log(f"[{started_at}] Starting: {script_info['label']}\n")
        self.log(f"> Working directory: {cwd}\n")
        self.log(f"> Python executable: {sys.executable}\n")
        self.log(f"> Command: {' '.join(cmd)}\n")
        self.log(f"> Script file: {script_info['file']}\n")
        if run_context:
            self.log(f"> Keyword file: {os.path.basename(run_context['keyword_file'])}\n")
            self.log(f"> Keyword count: {len(run_context['keywords'])}\n")
            self.log(f"> Topic slug: {run_context['topic_slug']}\n")
            if run_context["added_keywords"]:
                added = ", ".join(f"'{keyword}'" for keyword in run_context["added_keywords"])
                self.log(
                    f"> Added {len(run_context['added_keywords'])} new keywords to "
                    f"{os.path.basename(run_context['keyword_file'])}: {added}\n"
                )
            self.log(
                f"> Outputs: {output_names['output_xlsx']}, {output_names['output_json']}, "
                f"{output_names['output_md']}, {output_names['report_out']}, "
                f"{output_names['advisory_out']}, {output_names['feasibility_out']}\n"
            )
            if run_context.get("latest_json"):
                self.log(f"> Latest existing JSON input: {os.path.basename(run_context['latest_json'])}\n")
        self.log(f"> SERP_LOW_API_MODE={env['SERP_LOW_API_MODE']}\n")
        self.log(f"> SERP_BALANCED_MODE={env['SERP_BALANCED_MODE']}\n")
        self.log(f"> SERP_ENABLE_AI_QUERY_ALTERNATIVES={env['SERP_ENABLE_AI_QUERY_ALTERNATIVES']}\n")
        self.log(f"> SERP_DEEP_RESEARCH_MODE={env['SERP_DEEP_RESEARCH_MODE']}\n")
        if env.get("SERP_AI_PRIORITY_KEYWORDS"):
            self.log(
                f"> SERP_AI_PRIORITY_KEYWORDS={env['SERP_AI_PRIORITY_KEYWORDS'].replace('||', ', ')}\n"
            )
        else:
            self.log("> SERP_AI_PRIORITY_KEYWORDS=<none; A.1/A.2 skipped unless priority keywords are available>\n")
        self.log("> SERP_SINGLE_KEYWORD=<disabled; using keyword file management>\n")
        self.log("-" * 68 + "\n")
        self.run_btn.config(state="disabled")

        threading.Thread(target=self.execute_thread,
                         args=(cmd, env, cwd), daemon=True).start()

    def execute_thread(self, cmd, env, cwd):
        started_at = time.perf_counter()
        try:
            # Use Popen to capture output in real-time
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=cwd,
                env=env
            )

            for line in process.stdout:
                self.root.after(0, self.log, line)

            process.wait()
            elapsed_s = time.perf_counter() - started_at
            finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            status_label = self.EXIT_STATUS_LABELS.get(
                process.returncode, f"FAILED_{process.returncode}"
            )
            completed_script = os.path.basename(cmd[1]) if len(cmd) > 1 else ""
            self.root.after(
                0,
                self.log,
                f"\n[{finished_at}] Process finished with status {status_label} "
                f"(elapsed: {elapsed_s:.1f}s)\n" + "=" * 68 + "\n"
            )
            if process.returncode == 0 and completed_script == "run_pipeline.py":
                self.root.after(0, self.open_domain_override_review_after_pipeline)

        except Exception as e:
            elapsed_s = time.perf_counter() - started_at
            self.root.after(
                0,
                self.log,
                f"\n[Error starting process after {elapsed_s:.1f}s: {e}]\n" + "=" * 68 + "\n"
            )
        finally:
            self.root.after(0, self.refresh_keyword_file_options)
            self.root.after(0, lambda: self.run_btn.config(state="normal"))

    def log(self, message):
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, message)
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")

    def clear_log(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state="disabled")

    def on_low_api_mode_toggle(self):
        if self.low_api_mode_var.get():
            self.ai_query_alts_var.set(False)
            self.ai_query_alts_chk.state(["disabled"])
            self.balanced_mode_var.set(False)
            self.balanced_mode_chk.state(["disabled"])
            self.deep_research_mode_var.set(False)
            self.deep_research_mode_chk.state(["disabled"])
        else:
            self.ai_query_alts_chk.state(["!disabled"])
            self.balanced_mode_var.set(True)
            self.balanced_mode_chk.state(["!disabled"])
            self.deep_research_mode_chk.state(["!disabled"])

    def open_domain_override_review(self):
        paths = load_config_paths()
        json_path = os.path.join(os.getcwd(), paths["json"])
        overrides_path = os.path.join(os.getcwd(), paths["overrides"])
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log("\n" + "=" * 68 + "\n")
        self.log(f"[{started_at}] Starting: 6. Review Domain Override Candidates\n")
        self.log(f"> JSON source: {json_path}\n")
        self.log(f"> Overrides file: {overrides_path}\n")
        self.log("-" * 68 + "\n")

        try:
            data = load_json(json_path)
            overrides = load_overrides(overrides_path)
            classifier = EntityClassifier(override_file=overrides_path)
            candidates = collect_candidates(
                data,
                overrides,
                classifier,
                min_rows=4,
                min_keywords=2,
            )
            high_confidence, needs_judgment = split_candidates(candidates)
            self.log(
                f"Loaded {len(candidates)} candidates "
                f"({len(high_confidence)} high-confidence, {len(needs_judgment)} needs judgment).\n"
            )
            if not candidates:
                self.log("No domain override candidates found.\n")
                self.log(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Process finished with status SUCCESS (elapsed: 0.0s)\n" + "=" * 68 + "\n")
                messagebox.showinfo("Domain Override Review", "No domain override candidates were found in the current analysis.")
                return
            self.show_domain_override_review_window(
                candidates=candidates,
                high_confidence=high_confidence,
                overrides_path=overrides_path,
            )
            self.log("Opened checklist review window.\n")
            self.log(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Process finished with status SUCCESS (elapsed: 0.0s)\n" + "=" * 68 + "\n")
        except Exception as exc:
            self.log(f"Error: {exc}\n")
            self.log(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Process finished with status ERROR (elapsed: 0.0s)\n" + "=" * 68 + "\n")
            messagebox.showerror("Domain Override Review", str(exc))

    def open_domain_override_review_after_pipeline(self):
        paths = load_config_paths()
        json_path = os.path.join(os.getcwd(), paths["json"])
        overrides_path = os.path.join(os.getcwd(), paths["overrides"])
        try:
            data = load_json(json_path)
            overrides = load_overrides(overrides_path)
            classifier = EntityClassifier(override_file=overrides_path)
            candidates = collect_candidates(
                data,
                overrides,
                classifier,
                min_rows=4,
                min_keywords=2,
            )
            if not candidates:
                self.log("No domain override candidates found after pipeline completion.\n")
                return
            self.log("Full pipeline completed. Opening domain override review before content opportunities.\n")
            high_confidence, _needs_judgment = split_candidates(candidates)
            self.show_domain_override_review_window(
                candidates=candidates,
                high_confidence=high_confidence,
                overrides_path=overrides_path,
            )
        except Exception as exc:
            self.log(f"Unable to auto-open domain review after pipeline: {exc}\n")

    def show_domain_override_review_window(self, candidates, high_confidence, overrides_path):
        if self.domain_review_window and self.domain_review_window.winfo_exists():
            self.domain_review_window.destroy()

        self.domain_review_rows = []
        high_conf_domains = {item["domain"] for item in high_confidence}

        window = tk.Toplevel(self.root)
        window.title("Domain Override Candidate Review")
        window.geometry("980x640")
        window.transient(self.root)
        self.domain_review_window = window

        header = ttk.Frame(window)
        header.pack(fill="x", padx=12, pady=12)
        ttk.Label(
            header,
            text="Review candidate domains and check the ones you want to approve into domain_overrides.yml.",
            wraplength=860,
        ).pack(side="left", fill="x", expand=True)

        controls = ttk.Frame(window)
        controls.pack(fill="x", padx=12, pady=(0, 8))
        ttk.Button(
            controls,
            text="Refresh Candidates",
            command=self.open_domain_override_review,
        ).pack(side="left", padx=(0, 12))
        ttk.Button(
            controls,
            text="Check High-Confidence",
            command=lambda: self.set_domain_review_selection(mode="high_confidence"),
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            controls,
            text="Check All",
            command=lambda: self.set_domain_review_selection(mode="all"),
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            controls,
            text="Clear All",
            command=lambda: self.set_domain_review_selection(mode="none"),
        ).pack(side="left", padx=(0, 6))

        legend = ttk.LabelFrame(window, text="Category Colors")
        legend.pack(fill="x", padx=12, pady=(0, 8))
        for idx, entity_type in enumerate(ENTITY_TYPES):
            chip = tk.Label(
                legend,
                text=f" {entity_type} ",
                bg=self.DOMAIN_REVIEW_TAG_STYLES[entity_type]["background"],
                padx=6,
                pady=2,
                relief="groove",
                borderwidth=1,
            )
            chip.grid(row=idx // 4, column=idx % 4, padx=6, pady=4, sticky="w")

        columns = ("approve", "domain", "type", "confidence", "rows", "keywords", "best_rank", "section", "titles")
        tree_frame = ttk.Frame(window)
        tree_frame.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=18)
        tree.heading("approve", text="Approve")
        tree.heading("domain", text="Domain")
        tree.heading("type", text="Suggested Type")
        tree.heading("confidence", text="Confidence")
        tree.heading("rows", text="Rows")
        tree.heading("keywords", text="Keywords")
        tree.heading("best_rank", text="Best Rank")
        tree.heading("section", text="Group")
        tree.heading("titles", text="Sample Titles")

        tree.column("approve", width=75, anchor="center")
        tree.column("domain", width=190)
        tree.column("type", width=120, anchor="center")
        tree.column("confidence", width=90, anchor="center")
        tree.column("rows", width=60, anchor="center")
        tree.column("keywords", width=70, anchor="center")
        tree.column("best_rank", width=75, anchor="center")
        tree.column("section", width=130, anchor="center")
        tree.column("titles", width=320)
        for tag_name, style in self.DOMAIN_REVIEW_TAG_STYLES.items():
            tree.tag_configure(tag_name, **style)

        scrollbar_y = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        scrollbar_x = ttk.Scrollbar(tree_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scrollbar_y.grid(row=0, column=1, sticky="ns")
        scrollbar_x.grid(row=1, column=0, sticky="ew")
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        ordered_candidates = sorted(
            candidates,
            key=lambda item: (
                0 if item["domain"] in high_conf_domains else 1,
                -(item["source_keyword_count"]),
                -(item["organic_rows"]),
                item["domain"],
            ),
        )

        for item in ordered_candidates:
            selected = item["domain"] in high_conf_domains
            var = tk.BooleanVar(value=selected)
            item["selected_type"] = item.get("selected_type") or item["suggested_type"]
            section = "High-confidence" if selected else "Needs judgment"
            titles = "; ".join(item["sample_titles"])
            item_id = tree.insert(
                "",
                "end",
                values=(
                    "Yes" if selected else "No",
                    item["domain"],
                    item["selected_type"],
                    f"{item['confidence']:.1f}",
                    item["organic_rows"],
                    item["source_keyword_count"],
                    item["best_rank"] or "-",
                    section,
                    titles,
                ),
                tags=(self.domain_review_row_tag(item["selected_type"]),),
            )
            self.domain_review_rows.append({
                "tree_id": item_id,
                "variable": var,
                "candidate": item,
                "initial_high_confidence": selected,
                "is_high_confidence": selected,
            })

        tree.bind("<Double-1>", self.on_domain_review_toggle)
        tree.bind("<space>", self.on_domain_review_toggle)
        tree.bind("<<TreeviewSelect>>", self.on_domain_review_select)
        tree.bind("<Button-1>", self.on_domain_review_click)
        self.domain_review_tree = tree

        detail = ttk.LabelFrame(window, text="Selected Domain")
        detail.pack(fill="x", padx=12, pady=(0, 8))
        detail.columnconfigure(1, weight=1)
        ttk.Label(detail, text="Domain:").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self.domain_detail_domain_var = tk.StringVar(value="Select a row")
        ttk.Label(detail, textvariable=self.domain_detail_domain_var).grid(
            row=0, column=1, sticky="w", padx=8, pady=6
        )
        ttk.Label(detail, text="Suggested:").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        self.domain_detail_suggested_var = tk.StringVar(value="-")
        ttk.Label(detail, textvariable=self.domain_detail_suggested_var).grid(
            row=1, column=1, sticky="w", padx=8, pady=6
        )
        ttk.Label(detail, text="Override Type:").grid(row=2, column=0, sticky="w", padx=8, pady=6)
        self.domain_detail_type_var = tk.StringVar(value="")
        self.domain_detail_type_combo = ttk.Combobox(
            detail,
            textvariable=self.domain_detail_type_var,
            values=ENTITY_TYPES,
            state="readonly",
            width=28,
        )
        self.domain_detail_type_combo.grid(row=2, column=1, sticky="w", padx=8, pady=6)
        self.domain_detail_type_combo.bind(
            "<<ComboboxSelected>>",
            lambda _event: self.domain_detail_description_var.set(
                ENTITY_TYPE_DESCRIPTIONS.get(self.domain_detail_type_var.get(), "-")
            ),
        )
        ttk.Button(
            detail,
            text="Set Category For Selected Row",
            command=self.apply_domain_review_category,
        ).grid(row=2, column=2, sticky="w", padx=8, pady=6)
        ttk.Label(detail, text="Meaning:").grid(row=3, column=0, sticky="nw", padx=8, pady=6)
        self.domain_detail_description_var = tk.StringVar(value="-")
        ttk.Label(
            detail,
            textvariable=self.domain_detail_description_var,
            wraplength=700,
            justify="left",
        ).grid(row=3, column=1, columnspan=2, sticky="w", padx=8, pady=6)

        if self.domain_review_rows:
            first_id = self.domain_review_rows[0]["tree_id"]
            tree.selection_set(first_id)
            tree.focus(first_id)
            self.on_domain_review_select()

        footer = ttk.Frame(window)
        footer.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(
            footer,
            text="Approve Checked",
            command=lambda: self.apply_selected_domain_overrides(overrides_path),
        ).pack(side="right")
        ttk.Button(
            footer,
            text="Close",
            command=window.destroy,
        ).pack(side="right", padx=(0, 8))

    def on_domain_review_toggle(self, event=None):
        if not getattr(self, "domain_review_tree", None):
            return
        selection = self.domain_review_tree.selection()
        if not selection:
            return
        selected_id = selection[0]
        for row in self.domain_review_rows:
            if row["tree_id"] == selected_id:
                row["variable"].set(not row["variable"].get())
                self.refresh_domain_review_row(row)
                break

    def on_domain_review_click(self, event):
        if not getattr(self, "domain_review_tree", None):
            return
        self.destroy_inline_type_editor()
        row_id = self.domain_review_tree.identify_row(event.y)
        column_id = self.domain_review_tree.identify_column(event.x)
        if not row_id or not column_id:
            return

        self.domain_review_tree.selection_set(row_id)
        self.domain_review_tree.focus(row_id)
        self.on_domain_review_select()

        if column_id == "#1":
            for row in self.domain_review_rows:
                if row["tree_id"] == row_id:
                    row["variable"].set(not row["variable"].get())
                    self.refresh_domain_review_row(row)
                    return "break"

        if column_id == "#3":
            self.open_inline_type_editor(row_id)
            return "break"

        return None

    def on_domain_review_select(self, event=None):
        if not getattr(self, "domain_review_tree", None):
            return
        selection = self.domain_review_tree.selection()
        if not selection:
            self.domain_review_selected_row = None
            return
        selected_id = selection[0]
        for row in self.domain_review_rows:
            if row["tree_id"] == selected_id:
                self.domain_review_selected_row = row
                candidate = row["candidate"]
                chosen_type = candidate.get("selected_type") or candidate["suggested_type"]
                self.domain_detail_domain_var.set(candidate["domain"])
                self.domain_detail_suggested_var.set(
                    f"{candidate['suggested_type']} ({candidate['confidence']:.1f})"
                )
                self.domain_detail_type_var.set(chosen_type)
                self.domain_detail_description_var.set(
                    ENTITY_TYPE_DESCRIPTIONS.get(chosen_type, "-")
                )
                break

    def apply_domain_review_category(self):
        if not self.domain_review_selected_row:
            messagebox.showinfo("Domain Override Review", "Select a row first.")
            return
        chosen_type = self.domain_detail_type_var.get().strip()
        if chosen_type not in ENTITY_TYPES:
            messagebox.showerror("Domain Override Review", "Choose a valid entity type.")
            return
        row = self.domain_review_selected_row
        row["candidate"]["selected_type"] = chosen_type
        row["variable"].set(True)
        row["is_high_confidence"] = (
            row["initial_high_confidence"]
            and row["candidate"]["suggested_type"] == chosen_type
        )
        self.domain_detail_description_var.set(ENTITY_TYPE_DESCRIPTIONS[chosen_type])
        self.refresh_domain_review_row(row)
        self.destroy_inline_type_editor()

    def refresh_domain_review_row(self, row):
        section = "High-confidence" if row["is_high_confidence"] else "Needs judgment"
        candidate = row["candidate"]
        self.domain_review_tree.item(
            row["tree_id"],
            values=(
                "Yes" if row["variable"].get() else "No",
                candidate["domain"],
                candidate.get("selected_type") or candidate["suggested_type"],
                f"{candidate['confidence']:.1f}",
                candidate["organic_rows"],
                candidate["source_keyword_count"],
                candidate["best_rank"] or "-",
                section,
                "; ".join(candidate["sample_titles"]),
            ),
            tags=(self.domain_review_row_tag(candidate.get("selected_type") or candidate["suggested_type"]),),
        )

    def open_inline_type_editor(self, row_id):
        bbox = self.domain_review_tree.bbox(row_id, "#3")
        if not bbox:
            return
        x, y, width, height = bbox
        row = next((item for item in self.domain_review_rows if item["tree_id"] == row_id), None)
        if not row:
            return

        current_type = row["candidate"].get("selected_type") or row["candidate"]["suggested_type"]
        editor_var = tk.StringVar(value=current_type)
        editor = ttk.Combobox(
            self.domain_review_tree,
            textvariable=editor_var,
            values=ENTITY_TYPES,
            state="readonly",
            width=max(12, int(width / 9)),
        )
        editor.place(x=x, y=y, width=width, height=height)
        editor.focus_set()

        def commit_inline_edit(_event=None):
            row["candidate"]["selected_type"] = editor_var.get().strip()
            row["variable"].set(True)
            row["is_high_confidence"] = (
                row["initial_high_confidence"]
                and row["candidate"]["suggested_type"] == row["candidate"]["selected_type"]
            )
            if self.domain_review_selected_row and self.domain_review_selected_row["tree_id"] == row_id:
                self.domain_detail_type_var.set(row["candidate"]["selected_type"])
                self.domain_detail_description_var.set(
                    ENTITY_TYPE_DESCRIPTIONS.get(row["candidate"]["selected_type"], "-")
                )
            self.refresh_domain_review_row(row)
            self.destroy_inline_type_editor()

        editor.bind("<<ComboboxSelected>>", commit_inline_edit)
        editor.bind("<Return>", commit_inline_edit)
        editor.bind("<Escape>", lambda _event: self.destroy_inline_type_editor())
        editor.bind("<FocusOut>", lambda _event: self.destroy_inline_type_editor())
        self.inline_type_editor = editor
        editor.event_generate("<Button-1>")

    def destroy_inline_type_editor(self):
        if self.inline_type_editor is not None:
            try:
                self.inline_type_editor.destroy()
            except Exception:
                pass
            self.inline_type_editor = None

    def domain_review_row_tag(self, entity_type):
        tag = (entity_type or "").strip() or "unknown"
        return tag if tag in self.DOMAIN_REVIEW_TAG_STYLES else "unknown"

    def set_domain_review_selection(self, mode):
        for row in self.domain_review_rows:
            if mode == "all":
                row["variable"].set(True)
            elif mode == "none":
                row["variable"].set(False)
            elif mode == "high_confidence":
                row["variable"].set(row["is_high_confidence"])
            self.refresh_domain_review_row(row)

    def apply_selected_domain_overrides(self, overrides_path):
        selected_candidates = [
            {
                **row["candidate"],
                "selected_type": row["candidate"].get("selected_type") or row["candidate"]["suggested_type"],
            }
            for row in self.domain_review_rows
            if row["variable"].get()
        ]
        if not selected_candidates:
            messagebox.showinfo("Domain Override Review", "No domains are checked.")
            return

        existing_overrides = load_overrides(overrides_path)
        merged_overrides, added, skipped = merge_overrides(existing_overrides, selected_candidates)
        write_overrides(overrides_path, merged_overrides)

        paths = load_config_paths()
        refresh_result = refresh_analysis_outputs(
            json_path=os.path.join(os.getcwd(), paths["json"]),
            xlsx_path=os.path.join(os.getcwd(), paths["xlsx"]),
            overrides_path=overrides_path,
            candidates_report_path=os.path.join(os.getcwd(), paths["candidates_report"]),
        )

        self.log(f"Approved {len(selected_candidates)} checked candidates.\n")
        self.log(f"Added {len(added)} overrides to {overrides_path}.\n")
        for domain, entity_type in added:
            self.log(f"  + {domain}: {entity_type}\n")
        for domain, entity_type, reason in skipped:
            self.log(f"  = {domain}: {entity_type} ({reason})\n")
        self.log(
            "Refreshed local analysis outputs after override approval: "
            f"JSON changed {refresh_result['json_changed']} rows, "
            f"XLSX changed {refresh_result['xlsx_changed']} rows, "
            f"remaining candidates {refresh_result['candidate_count']}.\n"
        )
        self.log("You can run List Content Opportunities against the refreshed analysis now.\n")

        messagebox.showinfo(
            "Domain Override Review",
            "Updated overrides and refreshed analysis files.\n\n"
            f"Added: {len(added)}\n"
            f"Skipped existing: {len(skipped)}\n"
            f"JSON rows changed: {refresh_result['json_changed']}\n"
            f"XLSX rows changed: {refresh_result['xlsx_changed']}",
        )
        if self.domain_review_window and self.domain_review_window.winfo_exists():
            self.domain_review_window.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = SerpLauncherApp(root)
    root.mainloop()
