#!/usr/bin/env bash
# ============================================================
#  Call Intelligence Portal — One-command setup
#  Run:  bash setup.sh
# ============================================================
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

echo ""
echo "=============================================="
echo "  Call Intelligence Portal — Setup"
echo "=============================================="
echo ""

# ---- 1. Homebrew -----------------------------------------------------------
info "Checking Homebrew..."
if ! command -v brew &>/dev/null; then
  info "Installing Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
else
  success "Homebrew already installed"
fi

# ---- 2. ffmpeg + whisper.cpp -----------------------------------------------
info "Checking ffmpeg..."
if ! command -v ffmpeg &>/dev/null; then
  info "Installing ffmpeg..."
  brew install ffmpeg
else
  success "ffmpeg already installed"
fi

info "Checking whisper-cli..."
if ! command -v whisper-cli &>/dev/null; then
  info "Installing whisper.cpp..."
  brew install whisper-cpp
else
  success "whisper.cpp already installed"
fi

# ---- 3. Ollama + model -----------------------------------------------------
info "Checking Ollama..."
if ! command -v ollama &>/dev/null; then
  info "Installing Ollama..."
  brew install ollama
else
  success "Ollama already installed"
fi

info "Starting Ollama service (background)..."
ollama serve &>/dev/null &
sleep 3

info "Checking for llama3.2:3b model..."
if ! ollama list 2>/dev/null | grep -q "llama3.2:3b"; then
  info "Pulling llama3.2:3b (~2 GB, this may take a few minutes)..."
  ollama pull llama3.2:3b
else
  success "llama3.2:3b already available"
fi

# ---- 4. Python + Flask -----------------------------------------------------
info "Checking Python 3..."
if ! command -v python3 &>/dev/null; then
  error "Python 3 not found. Install from https://www.python.org/downloads/ and re-run."
fi
PY=$(python3 --version 2>&1 | awk '{print $2}')
success "Python $PY found"

info "Installing Python dependencies..."
python3 -m pip install -r requirements.txt --quiet
success "Python dependencies installed"

# ---- 5. Whisper model ------------------------------------------------------
MODEL_DIR="portal/models"
MODEL_FILE="$MODEL_DIR/ggml-base.en.bin"
mkdir -p "$MODEL_DIR"
if [ ! -f "$MODEL_FILE" ]; then
  info "Downloading Whisper base.en model (~141 MB)..."
  curl -L -o "$MODEL_FILE" \
    "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin"
  success "Whisper model downloaded"
else
  success "Whisper model already present"
fi

# ---- 6. Data directories ---------------------------------------------------
info "Creating data directories..."
mkdir -p portal/data/transcripts \
         portal/data/analysis \
         portal/data/scripts \
         portal/data/generated \
         portal/data/research
success "Data directories ready"

# ---- 7. Check for recordings -----------------------------------------------
echo ""
if [ ! -d "mcc" ] || [ -z "$(ls -A mcc 2>/dev/null)" ]; then
  warn "No recordings found in mcc/ folder."
  warn "Ask your team lead to copy the mcc/ folder here before running the pipeline."
  warn "Expected structure:  mcc/<campaign>/<disposition>/*.mp3"
else
  TOTAL=$(find mcc -name '*.mp3' | wc -l | tr -d ' ')
  success "Found $TOTAL recordings in mcc/"
fi

# ---- Done ------------------------------------------------------------------
echo ""
echo "=============================================="
echo -e "${GREEN}  Setup complete!${NC}"
echo "=============================================="
echo ""
echo "  NEXT STEPS:"
echo ""
echo "  1. Make sure the mcc/ folder is in this directory"
echo "     (copy it from your team lead / shared drive)"
echo ""
echo "  2. Run the pipeline to transcribe + analyse all calls:"
echo "       python3 portal/pipeline/run_daily.py"
echo ""
echo "  3. Start the portal:"
echo "       python3 portal/server.py"
echo ""
echo "  4. Open in browser:"
echo "       http://127.0.0.1:5000"
echo ""
