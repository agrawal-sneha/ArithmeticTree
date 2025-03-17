import os
import time
import subprocess
import selectors
import io
import sys
import argparse

###############################################################################
# Global Configurations
###############################################################################
BASE_DIR = "/content/ArithmeticTree"

# These directories must exist or be created.
MULT_LOGS_DIR = os.path.join(BASE_DIR, "mult_logs")
MCTS_LOGS_DIR = os.path.join(BASE_DIR, "mcts_mult_adder")
BACK_AND_FORTH_DIR = os.path.join(BASE_DIR, "back_and_forth")

# Create directories if they don't exist
os.makedirs(MULT_LOGS_DIR, exist_ok=True)
os.makedirs(MCTS_LOGS_DIR, exist_ok=True)
os.makedirs(BACK_AND_FORTH_DIR, exist_ok=True)

###############################################################################
# Argument Parser
###############################################################################
parser = argparse.ArgumentParser(description="multiplier design")
parser.add_argument("--input_bit", type=int, default=16, help="Bit-width of the multiplier")
parser.add_argument("--area_w", type=float, default=0.01, help="Weight for area in scoring")
args = parser.parse_args()

###############################################################################
# Subprocess Output Capture
###############################################################################
def capture_subprocess_output(subprocess_args):
    """
    Runs a subprocess and captures its output in real-time.
    Returns (success: bool, output: str).
    """
    process = subprocess.Popen(
        subprocess_args,
        bufsize=1,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True
    )
    buf = io.StringIO()

    def handle_output(stream, mask):
        line = stream.readline()
        buf.write(line)
        sys.stdout.write(line)

    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ, handle_output)

    # Poll until process completes
    while process.poll() is None:
        events = selector.select()
        for key, mask in events:
            callback = key.data
            callback(key.fileobj, mask)

    return_code = process.wait()
    selector.close()
    success = (return_code == 0)
    output = buf.getvalue()
    buf.close()
    return success, output

###############################################################################
# Utility Functions for Reading/Writing Files
###############################################################################
def get_best_file_from_ppo(strftime_str, input_bit):
    """
    Reads the PPO logs and returns (best_verilog_filename, best_data_line).
    """
    log_path = os.path.join(MULT_LOGS_DIR, f"mult_{input_bit}b_{strftime_str}.log")
    print("Looking for PPO log:", log_path)
    assert os.path.exists(log_path), f"[ERROR] {log_path} does not exist."

    best_score = float("inf")
    best_verilog_file = None
    best_data_line = None

    with open(log_path, "r") as fopen:
        for line in fopen:
            raw_line = line.strip()
            parts = raw_line.split("\t")
            # Expected format: file_name, lat1, lat2, pwr1, pwr2 (?)
            # The original code uses parts[1], parts[2], parts[3], parts[4]
            score = (float(parts[1]) +
                     float(parts[2]) * args.area_w +
                     float(parts[3]) +
                     float(parts[4]) * args.area_w)
            if score < best_score:
                best_score = score
                best_verilog_file = parts[0]
                best_data_line = raw_line

    return best_verilog_file, best_data_line

def get_best_file_from_mcts(strftime_str, input_bit):
    """
    Reads the MCTS logs and returns (best_verilog_filename, best_data_line).
    """
    log_path = os.path.join(MCTS_LOGS_DIR, f"mcts_mult_adder_{input_bit}b_openroad_{strftime_str}.log")
    print("Looking for MCTS log:", log_path)
    assert os.path.exists(log_path), f"[ERROR] {log_path} does not exist."

    best_score = float("inf")
    best_verilog_file = None
    best_data_line = None

    with open(log_path, "r") as fopen:
        for line in fopen:
            raw_line = line.strip()
            parts = raw_line.split("\t")
            score = (float(parts[1]) +
                     float(parts[2]) * args.area_w +
                     float(parts[3]) +
                     float(parts[4]) * args.area_w)
            if score < best_score:
                best_score = score
                best_verilog_file = parts[0]
                best_data_line = raw_line

    return best_verilog_file, best_data_line

def save_mult_file(verilog_file_name, strftime_str):
    """
    Copies lines from 'run_verilog_mult_mid/<verilog_file_name>' to
    'multiplier_template/mult_template_<strftime_str>.v' until the 'module adder(a,b,s);' line.
    """
    source_path = os.path.join(BASE_DIR, "run_verilog_mult_mid", verilog_file_name)
    dest_dir = os.path.join(BASE_DIR, "multiplier_template")
    os.makedirs(dest_dir, exist_ok=True)

    template_mult_name = f"mult_template_{strftime_str}.v"
    dest_path = os.path.join(dest_dir, template_mult_name)

    with open(source_path, "r") as fopen, open(dest_path, "w") as fwrite:
        for line in fopen:
            if not line.startswith("module adder(a,b,s);"):
                fwrite.write(line)
            else:
                break

    return template_mult_name

def save_adder_file(verilog_file_name, strftime_str, input_bit):
    """
    Copies lines from 'run_verilog_mult_add_mid/<verilog_file_name>' to
    'adder_template/adder_template_<strftime_str>.v', starting at 'module adder(a,b,s);'
    or skipping lines starting with '//' unless they do not contain '2'.
    """
    source_path = os.path.join(BASE_DIR, "run_verilog_mult_add_mid", verilog_file_name)
    dest_dir = os.path.join(BASE_DIR, "adder_template")
    os.makedirs(dest_dir, exist_ok=True)

    template_adder_name = f"adder_template_{strftime_str}.v"
    dest_path = os.path.join(dest_dir, template_adder_name)

    cnt = 0
    find_adder = False

    with open(source_path, "r") as fopen, open(dest_path, "w") as fwrite:
        for line in fopen:
            if not line.startswith("//"):
                if line.startswith("module adder(a,b,s);"):
                    find_adder = True
                if find_adder:
                    fwrite.write(line)
                else:
                    continue
            else:
                # For lines starting with '//'
                if "2" in line:
                    # skip lines with '2'
                    continue
                else:
                    if cnt < input_bit:
                        fwrite.write(line)
                        cnt += 1
    return template_adder_name

###############################################################################
# Main
###############################################################################
def main():
    input_bit = args.input_bit
    each_iter_ppo = 900
    each_iter_mcts = 100
    total_times = 3

    # Timestamp for logs/files
    timestamp = time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime())

    # Create a final log file in 'back_and_forth'
    final_log_path = os.path.join(
        BACK_AND_FORTH_DIR,
        f"bandf_{input_bit}b_{timestamp}_{args.area_w:.2f}.log"
    )
    flog = open(final_log_path, "w")

    start_time = time.time()

    for i in range(total_times):
        flog.write(f"Iteration {i}, Time elapsed: {time.time() - start_time:.2f} seconds\n")
        flog.flush()

        # Decide arguments for PPO2_mult.py
        ppo_cmd = [
            "python3",
            os.path.join(BASE_DIR, "PPO2_mult.py"),
            "--input_bit", str(input_bit),
            "--max_iter", str(each_iter_ppo),
            "--strftime", f"{timestamp}-{i}"
        ]

        # If not the first iteration, include the --template arg
        if i > 0:
            ppo_cmd.extend(["--template", template_adder_name])

        # Run PPO
        success, ppo_output = capture_subprocess_output(ppo_cmd)
        if not success:
            flog.write(f"[ERROR] PPO2_mult.py failed during iteration {i}.\nOutput:\n{ppo_output}\n")
            break

        # Now parse the PPO log file
        try:
            verilog_file_name, data_line = get_best_file_from_ppo(f"{timestamp}-{i}", input_bit)
            flog.write(f"PPO:\t{data_line}\n")
            flog.flush()
        except AssertionError as e:
            flog.write(str(e) + "\n")
            break

        # Save the multiplier file
        template_mult_name = save_mult_file(verilog_file_name, f"{timestamp}-{i}")

        # Decide arguments for MCTS_mult.py
        mcts_cmd = [
            "python3",
            os.path.join(BASE_DIR, "MCTS_mult.py"),
            "--input_bit", str(input_bit * 2),
            "--max_iter", str(each_iter_mcts),
            "--template", template_mult_name,
            "--strftime", f"{timestamp}-{i}",
            "--area_w", f"{args.area_w:.2f}"
        ]

        # If not the first iteration, add '--init_state'
        if i > 0:
            mcts_cmd.append("--init_state")

        # Run MCTS
        success, mcts_output = capture_subprocess_output(mcts_cmd)
        if not success:
            flog.write(f"[ERROR] MCTS_mult.py failed during iteration {i}.\nOutput:\n{mcts_output}\n")
            break

        # Now parse the MCTS log file
        try:
            verilog_file_name, data_line = get_best_file_from_mcts(f"{timestamp}-{i}", input_bit * 2)
            flog.write(f"MCTS\t{data_line}\n")
            flog.flush()
        except AssertionError as e:
            flog.write(str(e) + "\n")
            break

        # Save the adder file
        template_adder_name = save_adder_file(verilog_file_name, f"{timestamp}-{i}", input_bit * 2)

        # NOTE: This line increments i inside the loop. If that's intentional, keep it.
        # Otherwise, remove it or change your loop logic to avoid skipping iterations.
        i += 1

    # Final time
    total_time = time.time() - start_time
    flog.write(f"Total Time Elapsed: {total_time:.2f} seconds\n")
    flog.flush()
    flog.close()

###############################################################################
# Entry Point
###############################################################################
if __name__ == "__main__":
    main()
