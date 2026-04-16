# AMD Adrenalin VGM configuration (manual)

**Complete this before installing Ollama. Requires a reboot.**

GPU memory on Windows is set through AMD's Adrenalin driver UI — there is no command-line
equivalent on Windows. By default the GPU memory allocation is very conservative (4–8 GB),
which causes Ollama and llama.cpp to route 26B models to the CPU.

## Steps

1. Download AMD Software: Adrenalin Edition 25.8.1 WHQL or later
   - URL: https://www.amd.com/en/support/downloads/drivers.html
   - Category: Graphics → Integrated Graphics → Radeon 8060S

2. Run the installer. Reboot if prompted.

3. Open **AMD Software: Adrenalin Edition**

4. Go to: **Performance** → **Tuning** → **System** → **Variable Graphics Memory**

5. Change the dropdown to **Custom**

6. Enter **96** (GB)
   - Rationale: 96 GB GPU + 32 GB system RAM is the recommended split for LLM use.
   - 32 GB is sufficient for Windows 11, Chrome, VS Code, and the full Python agent stack.
   - Do not set to 128 GB — Windows needs at least 16–32 GB system RAM to operate.

7. Click **Apply**, then **Restart Now**

8. After reboot, re-run `infra\00_check_hardware.ps1` and confirm GPU VRAM ~96 GB

## Verification in Ollama after model load

```powershell
ollama ps
# The GPU column must show ~17 GB for gemma4-agent (not CPU, not 0)
```
