# Generic SLURM Cluster Guide

A practical guide for working with SLURM-managed HPC clusters. Covers the full lifecycle: SSH setup, job submission, monitoring, debugging, error handling, and resource management. Written so that any agent or developer with zero SLURM knowledge can confidently submit jobs, diagnose failures, and iterate.

---

## 1. Overview & Mental Model

### What is SLURM?

SLURM (**S**imple **L**inux **U**tility for **R**esource **M**anagement) is a job scheduler for High-Performance Computing (HPC) clusters. It manages a pool of compute nodes and allocates them to users on demand. You submit work as "jobs," and SLURM decides when and where each job runs based on available resources and priority.

### Login Nodes vs Compute Nodes

```
You (SSH) ──> Login Node ──> SLURM ──> Compute Node(s)
                │                         │
                │  (submit jobs here)      │  (heavy work runs here)
                │  (edit code, git, etc.)  │  (CPU/GPU/memory-intensive)
```

- **Login nodes**: Where you land after SSH. Use these for editing code, submitting jobs, checking status. **Never run heavy computation here** — it affects all users and may get your account flagged.
- **Compute nodes**: Where jobs actually execute. You get exclusive or shared access to these via SLURM.

### The 3 Job Commands

| Command | Purpose | When to use |
|---------|---------|-------------|
| `sbatch` | Submit a batch script to the queue | Production runs, unattended jobs |
| `salloc` | Request an interactive allocation | Debugging, iterative development |
| `srun`   | Run a command on an allocation | Execute commands within `salloc`, or inline single commands |

Think of it this way:
- `sbatch` = "run this script later when resources are available"
- `salloc` = "give me a compute node now, I'll run things interactively"
- `srun` = "run this specific command on my allocated node"

### Partitions, Accounts, and QOS

- **Partition**: A group of nodes with shared characteristics (e.g., `shared`, `gpu`, `large-memory`). Like "queues" in other schedulers.
- **Account**: Your billing/allocation group. Determines how many resources you can use.
- **QOS** (Quality of Service): Priority tiers that may offer different time limits or preemption rules.

List available partitions:
```bash
sinfo -o '%P %a %l %D %T %C'
```

Check your accounts:
```bash
sacctmgr show associations user=$USER format=Account,Partition,QOS
```

---

## 2. SSH Setup for Persistent Access

### SSH ControlMaster (Authenticate Once)

Add to `~/.ssh/config` on your local machine:

```
Host mycluster
    HostName login.cluster.example.edu
    User yourusername
    ControlMaster auto
    ControlPath ~/.ssh/sockets/%r@%h-%p
    ControlPersist 8h
    ServerAliveInterval 60
    ServerAliveCountMax 3
```

Then:
```bash
mkdir -p ~/.ssh/sockets
ssh mycluster   # authenticate once (password/TOTP/key) — good for ~8 hours
```

All subsequent `ssh mycluster` and `scp` commands reuse the existing connection with no re-authentication.

### SSHFS (Mount Cluster Filesystem Locally)

Mount the cluster filesystem so you can browse files with local tools:

```bash
mkdir -p ~/mnt/cluster
sshfs mycluster:/path/to/your/workspace ~/mnt/cluster \
  -o reconnect,ServerAliveInterval=15,ServerAliveCountMax=3
```

Unmount when done:
```bash
# Linux
fusermount -u ~/mnt/cluster

# macOS
umount ~/mnt/cluster 2>/dev/null || diskutil unmount force ~/mnt/cluster
```

### tmux for Persistent Sessions

Always run long-lived processes (like `salloc`) inside tmux so they survive SSH disconnects:

```bash
ssh mycluster
tmux new -s work          # create named session
# ... do work ...
# Ctrl-b d                # detach (session keeps running)
tmux attach -t work       # reattach later
```

---

## 3. Interactive Debugging (`salloc` + `srun`)

Interactive debugging is the fastest way to iterate: you grab a compute node once and reuse it for hours.

### Step 1: Get an Allocation

```bash
ssh mycluster
tmux new -s debug

salloc --account=myaccount --partition=shared \
       --nodes=1 --ntasks=1 --cpus-per-task=8 \
       --mem=32G --time=02:00:00 --job-name=debug

# Save the job ID for use from other terminals
echo $SLURM_JOB_ID > ~/.debug_jobid
```

Detach tmux (`Ctrl-b d`). The allocation stays alive.

### Step 2: Run Commands on the Compute Node

From any SSH session (even a new terminal):

```bash
JOBID=$(cat ~/.debug_jobid)

# Run a single command
srun --jobid=$JOBID --overlap python my_script.py --input data.csv

# Run an interactive shell on the compute node
srun --jobid=$JOBID --overlap --pty bash
```

The `--overlap` flag allows multiple `srun` commands on the same allocation simultaneously.

### Why This is Fast

- `sbatch` puts your job in a queue — it may wait minutes or hours.
- `salloc` waits once for allocation, then all `srun` commands execute immediately (no queue).
- Typical cycle: edit code → `srun` test → see results in seconds.

### Resource Sizing Tips

| Use case | CPUs | Memory | Notes |
|----------|------|--------|-------|
| Quick debugging | 4-8 | 16-32G | Allocates fast, good for single-file testing |
| Medium workload | 16 | 64G | Parallel processing, moderate datasets |
| Heavy processing | 32-64 | 128-256G | Large datasets, many workers |

Start small. You can always cancel (`scancel $JOBID`) and request more.

---

## 4. Batch Jobs (`sbatch`)

Batch jobs run unattended. You write a script with resource directives and SLURM runs it when resources are available.

### Job Script Anatomy

```bash
#!/bin/bash
#SBATCH --job-name=my-job
#SBATCH --account=myaccount
#SBATCH --partition=shared
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=01:00:00
#SBATCH --output=logs/%j_stdout.log
#SBATCH --error=logs/%j_stderr.log

# --- Script body (runs on compute node) ---

# Load modules if needed
module load python/3.10

# Activate environment
source /path/to/venv/bin/activate

# Run your code
python process_data.py --input "$1"
```

### Key `#SBATCH` Directives

| Directive | Purpose | Example |
|-----------|---------|---------|
| `--job-name` | Human-readable job name | `--job-name=train-model` |
| `--partition` | Which node pool to use | `--partition=gpu` |
| `--account` | Billing/allocation account | `--account=mygroup` |
| `--nodes` | Number of nodes | `--nodes=1` |
| `--ntasks-per-node` | Processes per node | `--ntasks-per-node=1` |
| `--cpus-per-task` | CPU cores per process | `--cpus-per-task=16` |
| `--mem` | Memory per node | `--mem=64G` |
| `--time` | Wall clock limit (HH:MM:SS) | `--time=04:00:00` |
| `--output` | Stdout log path | `--output=logs/%j.out` |
| `--error` | Stderr log path | `--error=logs/%j.err` |
| `--array` | Array job specification | `--array=1-100%10` |
| `--gpus` | GPU count (if supported) | `--gpus=1` |
| `--mail-type` | Email notifications | `--mail-type=END,FAIL` |
| `--mail-user` | Email address | `--mail-user=you@example.com` |

### Log Path Substitution Variables

| Variable | Meaning |
|----------|---------|
| `%j` | Job ID |
| `%A` | Array job ID (parent) |
| `%a` | Array task index |
| `%x` | Job name |
| `%N` | Short hostname |

### Submit and Check

```bash
# Create log directory first
mkdir -p logs

# Submit
sbatch my_job.sh
# Output: Submitted batch job 12345678

# Check status
squeue -u $USER
```

---

## 5. Array Jobs In Depth

Array jobs run the same script many times with different inputs. Each task gets a unique index via `$SLURM_ARRAY_TASK_ID`.

### When to Use

- Processing many independent files/datasets with the same script
- Parameter sweeps
- Any embarrassingly parallel workload

### Basic Array Job

```bash
#!/bin/bash
#SBATCH --job-name=process-all
#SBATCH --account=myaccount
#SBATCH --partition=shared
#SBATCH --array=1-100
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=logs/%A_%a.out
#SBATCH --error=logs/%A_%a.err

# Read the Nth line from a file list
ITEM=$(sed -n "${SLURM_ARRAY_TASK_ID}p" input_list.txt)

echo "Processing: $ITEM"
python process.py --input "$ITEM"
```

### Throttling Concurrent Tasks

Limit how many tasks run simultaneously to avoid overwhelming shared resources:

```bash
#SBATCH --array=1-500%20    # 500 tasks, max 20 running at once
```

This is important when:
- Tasks hit the same filesystem heavily (NFS bottleneck)
- You share an account with others and don't want to monopolize the queue
- Tasks use a shared database or API

### Preparing the Input List

```bash
# List files
ls /data/inputs/*.csv > input_list.txt

# Or generate programmatically
python -c "
for i in range(1, 101):
    print(f'dataset_{i:04d}')
" > input_list.txt

# Count items (this is your array range)
wc -l < input_list.txt
# Output: 100
# Use: --array=1-100
```

### Reading Array Results

```bash
# Check which tasks succeeded
for f in logs/12345678_*.out; do
    task_id=$(echo "$f" | grep -oP '(?<=_)\d+(?=\.out)')
    if grep -q "SUCCESS" "$f"; then
        echo "Task $task_id: OK"
    else
        echo "Task $task_id: FAILED"
    fi
done
```

---

## 6. Monitoring & Inspecting Jobs

### While Jobs are Running

```bash
# See all your jobs
squeue -u $USER

# Detailed view of one job
squeue -j JOBID -o '%.18i %.9P %.30j %.8T %.10M %.6D %R'

# Watch jobs update in real-time
watch -n 5 'squeue -u $USER'

# Tail output logs while a job runs
tail -f logs/12345678.out

# For array jobs, tail a specific task
tail -f logs/12345678_42.out
```

### `squeue` Output Columns

| Column | Meaning |
|--------|---------|
| `JOBID` | Job ID (with array index for array tasks) |
| `PARTITION` | Which partition |
| `NAME` | Job name |
| `ST` | State: `R`=running, `PD`=pending, `CG`=completing |
| `TIME` | Elapsed time |
| `NODES` | Number of nodes |
| `NODELIST(REASON)` | Node name, or reason it's pending |

### Common Pending Reasons

| Reason | Meaning |
|--------|---------|
| `Priority` | Other jobs have higher priority — wait |
| `Resources` | Not enough free resources — wait |
| `QOSMaxJobsPerUserLimit` | You hit a per-user job limit |
| `AssocGrpCPUMinutesLimit` | Your account's CPU allocation is exhausted |
| `Dependency` | Waiting on another job to finish |

### After Jobs Complete

```bash
# Job accounting (resource usage, exit status)
sacct -j JOBID --format=JobID,JobName,State,Elapsed,MaxRSS,MaxVMSize,ExitCode

# Full job details (even after completion)
scontrol show job JOBID

# See all your recent jobs
sacct -u $USER --starttime=2026-03-01 --format=JobID,JobName,State,Elapsed,MaxRSS
```

### Cluster Status

```bash
# Partition availability
sinfo -p shared -o '%P %a %l %D %T %C'

# Node-level detail
sinfo -N -p shared -o '%N %T %C %m %e'

# Your allocation usage
sacctmgr show associations user=$USER format=Account,Partition,GrpTRESMins,GrpTRES
```

---

## 7. Common Failure Modes & How to Fix Them

### OOM Killed (Out of Memory)

**Symptoms:**
- `sacct` shows state `OUT_OF_MEMORY`
- Stderr: `slurmstepd: error: Detected 1 oom_kill event`
- Process killed with signal 9 (SIGKILL)

**Diagnosis:**
```bash
sacct -j JOBID --format=JobID,State,MaxRSS,ReqMem,ExitCode
```

**Fixes:**
- Increase `--mem` (e.g., 32G → 64G → 128G)
- Reduce parallelism (fewer `--cpus-per-task` means fewer workers competing for memory)
- Process data in smaller chunks
- Use memory-mapped files or generators instead of loading everything into RAM

### Timeout

**Symptoms:**
- `sacct` shows state `TIMEOUT`
- Job killed exactly at the `--time` limit

**Fixes:**
- Increase `--time` (check partition limits: `sinfo -p PARTITION -o '%l'`)
- Reduce workload per job (split into more array tasks)
- Add checkpointing so interrupted jobs can resume
- Profile to find bottlenecks

### Stale File Handle (NFS)

**Symptoms:**
- `OSError: [Errno 116] Stale file handle`
- Often happens right after job starts

**Fixes:**
```bash
# Add a brief delay at the start of your script
sleep 2

# Or force NFS cache refresh
ls /path/to/data/ > /dev/null 2>&1
sleep 1
```

This is an NFS metadata caching issue — the compute node's NFS client has stale cached data. A brief delay or directory listing forces a cache refresh.

### Node Failure

**Symptoms:**
- `sacct` shows state `NODE_FAIL`
- No useful output in logs

**Fix:** Simply resubmit. This is a hardware issue, not your fault.

```bash
sbatch my_job.sh   # resubmit
```

### Disk Full

**Symptoms:**
- `OSError: [Errno 28] No space left on device`
- Write operations fail

**Diagnosis:**
```bash
df -h /path/to/output/    # check filesystem usage
du -sh ~/                  # check your home directory
```

**Fixes:**
- Clean up old logs, temp files, checkpoints
- Write output to a different filesystem (e.g., scratch vs home)
- Check if you have a quota: `quota -s` or cluster-specific commands

### Permission Errors

**Symptoms:**
- `PermissionError: [Errno 13] Permission denied`
- Can't write to shared directories or create lock files

**Fixes:**
- Check file ownership: `ls -la /path/to/file`
- Use a writable directory for output (your home or scratch space)
- For read-only datasets, copy to a writable location first
- Check group permissions: `id` to see your groups

### Module Not Found

**Symptoms:**
- `ModuleNotFoundError: No module named 'mypackage'`
- Works on login node but not compute node

**Fixes:**
- Activate your virtual environment in the job script (before running Python)
- Use absolute paths to the Python interpreter
- Make sure the environment is on a shared filesystem accessible from compute nodes

---

## 8. Resource Management Patterns

### Start Small, Scale Up

Don't guess resource requirements. Start with a small allocation and increase based on actual usage:

```
Step 1:  4 CPU,  16G  →  Run one item, check sacct for actual usage
Step 2:  8 CPU,  32G  →  Run a batch, monitor MaxRSS
Step 3: 16 CPU,  64G  →  Scale up if needed
Step 4: 32 CPU, 128G  →  For genuinely large workloads
```

### Check Actual Resource Usage

After a job completes:
```bash
sacct -j JOBID --format=JobID,Elapsed,MaxRSS,MaxVMSize,AveCPU,ExitCode
```

- **MaxRSS**: Peak memory (resident set size). Your `--mem` should be ~20-50% higher than this.
- **Elapsed**: Actual wall time. Your `--time` should be ~50-100% higher than this.
- **AveCPU**: Average CPU time. If much less than wall time × CPUs, you're over-requesting CPUs.

### Memory vs CPUs Tradeoff

More CPUs often means more memory usage (parallel workers each hold data in memory):

```bash
# If OOM with 16 CPUs / 64G, try FEWER CPUs first:
--cpus-per-task=8 --mem=64G     # fewer workers = less memory

# Only increase memory if that doesn't help:
--cpus-per-task=16 --mem=128G
```

### Estimating from First Run

```bash
# Run one task with generous resources
sbatch --cpus-per-task=8 --mem=64G --time=04:00:00 single_test.sh

# After it completes, check what it actually used
sacct -j JOBID --format=MaxRSS,Elapsed,AveCPU

# Example output:
#    MaxRSS    Elapsed     AveCPU
#    12.5G    00:45:23   00:38:12

# Good settings for production:
# --mem=20G (12.5G × 1.5 buffer)
# --time=01:30:00 (45min × 2 buffer)
# --cpus-per-task=8 (CPU was well-utilized)
```

---

## 9. Python Environment Management on Clusters

### Virtual Environments on Shared Filesystems

Create your venv on a filesystem accessible from all nodes:

```bash
# On the login node
cd /shared/workspace/myproject
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

In job scripts, always activate the same venv:
```bash
source /shared/workspace/myproject/.venv/bin/activate
python my_script.py
```

### Using `uv` vs `pip`

[`uv`](https://github.com/astral-sh/uv) is dramatically faster than `pip` for installs:

```bash
# Install uv (one-time)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Use uv instead of pip
uv pip install numpy pandas scikit-learn    # 10-100x faster than pip
uv pip install -r requirements.txt
```

### Safe Installs with `--no-deps`

When updating a single package without disturbing the rest of your environment:

```bash
# Install/upgrade only this package, don't touch dependencies
uv pip install --no-deps -e /path/to/mypackage

# Or with pip
pip install --no-deps -e /path/to/mypackage
```

This is critical when:
- You have a package installed from source (e.g., a fork) and don't want it replaced by PyPI
- You're iterating on a single package in a complex environment

### Editable Installs for Rapid Iteration

```bash
# Install in editable mode — changes to source take effect immediately
uv pip install --no-deps -e /path/to/mypackage
```

With editable installs, you can:
1. Edit code on the cluster (or push via git)
2. Run your script — it picks up changes without reinstalling
3. Only reinstall if you change package metadata (setup.py/pyproject.toml)

### Binary Compatibility

Watch out for compiled extension mismatches:

```bash
# This can break things:
pip install numpy==1.26.0   # pandas/scipy were compiled against numpy 1.24

# If you see errors like "numpy.core.multiarray failed to import", rebuild:
pip install --force-reinstall numpy pandas scipy
```

---

## 10. Workflow Patterns for Agents

### Pattern 1: Debug Loop (Interactive)

Fast iteration for fixing issues one at a time:

```
1. Edit code locally
2. Push to remote: git push
3. Pull on cluster: ssh mycluster "cd /path/to/project && git pull"
4. Install changes: ssh mycluster "source .venv/bin/activate && uv pip install --no-deps -e ."
5. Run on compute node: ssh mycluster "srun --jobid=JOBID --overlap python test.py"
6. Check output → go to step 1 if needed
```

Cycle time: ~1-3 minutes per iteration.

### Pattern 2: Batch Validation

Process many items and collect results:

```bash
# 1. Create input list
python -c "
import os
for f in sorted(os.listdir('/data/inputs')):
    print(f)
" > item_list.txt

# 2. Write job script (process_all.sh)
cat > process_all.sh << 'SCRIPT'
#!/bin/bash
#SBATCH --array=1-$(wc -l < item_list.txt)%20
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=logs/%A_%a.out
#SBATCH --error=logs/%A_%a.err

ITEM=$(sed -n "${SLURM_ARRAY_TASK_ID}p" item_list.txt)
echo "ITEM: $ITEM"
python process.py --input "$ITEM" && echo "SUCCESS" || echo "FAILED"
SCRIPT

# 3. Submit
mkdir -p logs
sbatch process_all.sh

# 4. Monitor
watch -n 10 'squeue -u $USER'

# 5. Parse results (after completion)
grep -l "SUCCESS" logs/JOBID_*.out | wc -l    # count successes
grep -l "FAILED" logs/JOBID_*.out              # list failures
```

### Pattern 3: Retry Failed Tasks

After a batch run, retry only the failures:

```bash
# Find failed tasks and extract their items
for f in logs/JOBID_*.out; do
    if grep -q "FAILED" "$f"; then
        task_id=$(echo "$f" | grep -oP '\d+(?=\.out)')
        sed -n "${task_id}p" item_list.txt
    fi
done > retry_list.txt

echo "Retrying $(wc -l < retry_list.txt) failed items"

# Submit retry job with more resources
sbatch --array=1-$(wc -l < retry_list.txt)%10 \
       --mem=64G --time=02:00:00 \
       process_all.sh   # script reads from retry_list.txt now
```

### Pattern 4: Progressive Resource Escalation

When you don't know how much resource a task needs:

```bash
# Round 1: Try with modest resources
sbatch --mem=32G --time=01:00:00 --array=1-100%20 job.sh

# Check failures
sacct -j JOBID --format=JobID,State,MaxRSS | grep -E 'OUT_OF_MEMORY|TIMEOUT'

# Round 2: Retry OOM failures with more memory
sbatch --mem=64G --time=01:00:00 --array=... job.sh

# Round 3: Retry remaining with even more
sbatch --mem=128G --time=02:00:00 --array=... job.sh

# Round 4: Full node for the hardest cases
sbatch --mem=200G --time=04:00:00 --array=... job.sh
```

### Categorizing Batch Results

```bash
JOBID=12345678

# Count by outcome
echo "=== Results ==="
echo "Success: $(grep -rl 'SUCCESS' logs/${JOBID}_*.out 2>/dev/null | wc -l)"
echo "Failed:  $(grep -rl 'FAILED' logs/${JOBID}_*.out 2>/dev/null | wc -l)"

# Check for OOM in stderr
echo "OOM:     $(grep -rl 'oom_kill' logs/${JOBID}_*.err 2>/dev/null | wc -l)"

# Check for timeouts
echo "Timeout: $(sacct -j $JOBID --format=State --noheader | grep -c TIMEOUT)"
```

---

## 11. Useful One-Liners Reference

### Job Management

```bash
# Cancel a job
scancel JOBID

# Cancel all your jobs
scancel -u $USER

# Cancel all pending jobs (keep running ones)
scancel -u $USER --state=PENDING

# Hold/release a pending job
scontrol hold JOBID
scontrol release JOBID
```

### Counting Successes and Failures

```bash
# Count SUCCESS/FAILED across array job outputs
JOBID=12345678
echo "Success: $(grep -rl 'SUCCESS' logs/${JOBID}_*.out | wc -l)"
echo "Failed:  $(grep -rl 'FAILED' logs/${JOBID}_*.out | wc -l)"
```

### Finding Which Tasks Are Still Running

```bash
squeue -j JOBID -o '%i %T %M' --noheader
```

### Checking Stderr for OOM Kills

```bash
grep -rl "oom_kill\|Out of memory\|Killed" logs/${JOBID}_*.err
```

### Getting the Input Item from a Task's Output

```bash
# If your script prints "ITEM: <name>" at the start
grep "^ITEM:" logs/${JOBID}_42.out
```

### Resubmitting Only Failed Tasks

```bash
# Build comma-separated list of failed task IDs
FAILED=$(for f in logs/${JOBID}_*.out; do
    id=$(basename "$f" | grep -oP '(?<=_)\d+(?=\.out)')
    grep -q "FAILED" "$f" && echo -n "$id,"
done)
FAILED=${FAILED%,}  # remove trailing comma

# Resubmit just those tasks
sbatch --array=$FAILED job.sh
```

### Quick Resource Check After a Job

```bash
sacct -j JOBID --format=JobID%-20,State,Elapsed,MaxRSS,MaxVMSize,ExitCode --noheader
```

### Find Your Biggest Memory Users

```bash
sacct -u $USER --starttime=$(date -d '7 days ago' +%Y-%m-%d) \
      --format=JobID,JobName,MaxRSS,State --noheader | sort -k3 -h | tail -20
```

### Estimate Queue Wait Time

```bash
# See how many jobs are ahead of you
squeue -p shared --state=PENDING -o '%i %u %T %S' | head -20

# Check recent start times for similar jobs
sacct -u $USER --format=JobID,Submit,Start,Elapsed --starttime=$(date -d '1 day ago' +%Y-%m-%d)
```

---

## Quick Reference Card

```
SUBMIT      sbatch job.sh                     Submit batch job
            salloc --partition=P --mem=XG     Get interactive allocation
            srun --jobid=ID cmd               Run on allocation

MONITOR     squeue -u $USER                   Your jobs
            sacct -j ID --format=...          Job accounting
            scontrol show job ID              Full job details
            sinfo -p P                        Partition status

CANCEL      scancel ID                        Cancel one job
            scancel -u $USER                  Cancel all your jobs

LOGS        %j = job ID                       In --output/--error paths
            %A = array parent ID
            %a = array task index

STATES      R  = Running        PD = Pending
            CG = Completing     CD = Completed
            F  = Failed         TO = Timeout
            OOM = Out of Memory NF = Node Fail
```
