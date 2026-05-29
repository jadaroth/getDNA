import streamlit as st
import pandas as pd
import requests
import time
import io
from pathlib import Path

st.set_page_config(
    page_title="UCSC Sequence Fetcher",
    page_icon="🧬",
    layout="centered",
)

# ── UCSC REST helper ──────────────────────────────────────────────────────────
UCSC_API = "https://api.genome.ucsc.edu/getData/sequence"

GENOME_ALIASES = {
    "hg38": "hg38", "grch38": "hg38", "grch38/hg38": "hg38",
    "hg19": "hg19", "grch37": "hg19",
    "hg18": "hg18", "ncbi36": "hg18",
    "mm39": "mm39", "grcm39": "mm39",
    "mm10": "mm10", "grcm38": "mm10",
    "mm9":  "mm9",
    "rn7":  "rn7",
    "danrer11": "danRer11", "danrer10": "danRer10",
    "dm6":  "dm6", "dm3": "dm3",
    "ce11": "ce11", "saccer3": "sacCer3",
}

def normalise_genome(g: str) -> str:
    return GENOME_ALIASES.get(g.lower().strip(), g.strip())

def normalise_chrom(chrom: str) -> str:
    c = str(chrom).strip()
    if not c.lower().startswith("chr"):
        c = "chr" + c
    return c

def fetch_sequence(chrom: str, start: int, end: int, genome: str) -> tuple[str, str]:
    chrom  = normalise_chrom(chrom)
    genome = normalise_genome(genome)
    params = {"genome": genome, "chrom": chrom, "start": start, "end": end}
    try:
        r = requests.get(UCSC_API, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        if "dna" in data:
            return data["dna"].upper(), ""
        elif "error" in data:
            return "", data["error"]
        else:
            return "", f"Unexpected response: {data}"
    except requests.exceptions.Timeout:
        return "", "Request timed out"
    except requests.exceptions.HTTPError as e:
        return "", f"HTTP {e.response.status_code}"
    except Exception as e:
        return "", str(e)

DELAY   = 0.3      # seconds between UCSC API calls
MAX_LEN = 1_000_000  # max region length in bp

# ── Template files (bundled inline) ──────────────────────────────────────────
def make_template_bytes() -> tuple[bytes, bytes]:
    """Return (csv_bytes, xlsx_bytes) for the downloadable template."""
    template_df = pd.DataFrame({
        "chrom":  ["chr7",    "chr17",   "chr1",    "chrX"],
        "start":  [117548628, 7668402,   1000000,   48649700],
        "end":    [117548828, 7668602,   1000200,   48649900],
        "genome": ["hg38",    "hg38",    "hg19",    "mm10"],
    })
    csv_bytes = template_df.to_csv(index=False).encode()
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        template_df.to_excel(writer, index=False, sheet_name="Coordinates")
        ws = writer.sheets["Coordinates"]
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = (
                max(len(str(c.value or "")) for c in col) + 4
            )
    return csv_bytes, buf.getvalue()

# ── Main UI ───────────────────────────────────────────────────────────────────
st.title("🧬 UCSC Sequence Fetcher")
st.write(
    "Upload a CSV or Excel file with genomic coordinates. "
    "The app queries the **UCSC Genome Browser REST API** and appends a `sequence` column to your file."
)

st.subheader("📋 How to use")
st.markdown(
    """
1. Download the template below and fill in your coordinates, or format your own file with these columns:
   - **`chrom`** — chromosome name (e.g. `chr7` or `7`)
   - **`start`** — start position, 0-based (BED-style)
   - **`end`** — end position, exclusive
   - **`genome`** — UCSC assembly name (e.g. `hg38`, `hg19`, `mm10`)
2. Upload your file and click **Fetch Sequences**.
3. Download the result with the new `sequence` column appended.
"""
)

tmpl_csv, tmpl_xlsx = make_template_bytes()
col_t1, col_t2, _ = st.columns([1, 1, 2])
col_t1.download_button(
    label="📄 Download template CSV",
    data=tmpl_csv,
    file_name="template.csv",
    mime="text/csv",
    use_container_width=True,
)
col_t2.download_button(
    label="📊 Download template Excel",
    data=tmpl_xlsx,
    file_name="template.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    use_container_width=True,
)

st.divider()
uploaded = st.file_uploader("Upload your CSV or Excel file", type=["csv", "xlsx", "xls"])

if uploaded is None:
    st.stop()

# ── Load file ─────────────────────────────────────────────────────────────────
ext = Path(uploaded.name).suffix.lower()
try:
    df = pd.read_csv(uploaded) if ext == ".csv" else pd.read_excel(uploaded)
except Exception as e:
    st.error(f"Could not read file: {e}")
    st.stop()

st.write(f"✅ File loaded successfully! **{len(df):,} rows**, {len(df.columns)} columns")
st.dataframe(df.head())

# ── Validate columns ──────────────────────────────────────────────────────────
required = {"chrom", "start", "end", "genome"}
missing  = required - set(df.columns.str.lower())
if missing:
    st.error(f"Missing required column(s): {', '.join(sorted(missing))}")
    st.stop()

df.columns = [c.lower() for c in df.columns]

# ── Run button ────────────────────────────────────────────────────────────────
if st.button("Fetch Sequences 🔍"):
    sequences, errors = [], []

    progress = st.progress(0, text="Starting…")
    n = len(df)

    for i, row in df.iterrows():
        coord = f"{row['chrom']}:{row['start']}-{row['end']} ({row['genome']})"
        progress.progress(int((i / n) * 100), text=f"Row {i+1}/{n} — {coord}")

        try:
            length = int(row["end"]) - int(row["start"])
        except (ValueError, TypeError):
            sequences.append(""); errors.append("Invalid start/end values"); continue

        if length <= 0:
            sequences.append(""); errors.append("end ≤ start"); continue

        if length > MAX_LEN:
            sequences.append(""); errors.append(f"Region too large ({length:,} bp)"); continue

        seq, err = fetch_sequence(str(row["chrom"]), int(row["start"]), int(row["end"]), str(row["genome"]))
        sequences.append(seq)
        errors.append(err)

        if DELAY > 0:
            time.sleep(DELAY)

    progress.progress(100, text="Done!")

    df["sequence"]    = sequences
    df["fetch_error"] = errors

    ok_count  = sum(1 for e in errors if not e)
    err_count = sum(1 for e in errors if e)

    if err_count:
        st.warning(f"✅ {ok_count} sequences fetched — ⚠️ {err_count} rows had errors (see `fetch_error` column)")
    else:
        st.write(f"✅ {ok_count} sequences fetched successfully!")

    # Preview
    st.subheader("Results preview")
    preview = df[["chrom", "start", "end", "genome", "sequence", "fetch_error"]].copy()
    preview["sequence"] = preview["sequence"].apply(lambda s: s[:60] + "…" if len(s) > 60 else s)
    st.dataframe(preview)

    # Build output
    out_df = df.copy()
    if out_df["fetch_error"].eq("").all():
        out_df = out_df.drop(columns=["fetch_error"])

    st.subheader("Download enriched file")
    col1, col2 = st.columns(2)

    csv_bytes = out_df.to_csv(index=False).encode()
    col1.download_button(
        label="📥 Download CSV",
        data=csv_bytes,
        file_name=Path(uploaded.name).stem + "_sequences.csv",
        mime="text/csv",
        use_container_width=True,
    )

    xlsx_buf = io.BytesIO()
    with pd.ExcelWriter(xlsx_buf, engine="openpyxl") as writer:
        out_df.to_excel(writer, index=False, sheet_name="Sequences")
        ws = writer.sheets["Sequences"]
        for col in ws.columns:
            max_w = max((len(str(cell.value or "")) for cell in col), default=10)
            ws.column_dimensions[col[0].column_letter].width = min(max_w + 2, 60)
    col2.download_button(
        label="📥 Download Excel",
        data=xlsx_buf.getvalue(),
        file_name=Path(uploaded.name).stem + "_sequences.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
