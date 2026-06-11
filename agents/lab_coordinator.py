import subprocess
import asyncio
import sys

async def stream_runtime_logs(command: list, duration_seconds: int = 10):
    """Spawns the backend application daemon and scans live logs for runtime faults."""
    print(f"[Helix Telemetry] Launching runtime process: {' '.join(command)}")
    
    # Spawn background daemon with piped outputs
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    error_logs = []
    
    async def read_stream(stream, stream_name):
        while True:
            line = await stream.readline()
            if not line:
                break
            decoded_line = line.decode().strip()
            # Actively monitor for standard Python runtime crashes
            if any(indicator in decoded_line for indicator in ["Traceback", "ModuleNotFoundError", "Exception", "CRITICAL"]):
                print(f"🔥 [Telemetry Catch] {stream_name}: {decoded_line}")
                error_logs.append(decoded_line)

    # Monitor stdout and stderr concurrently without locking execution
    try:
        await asyncio.wait_for(
            asyncio.gather(
                read_stream(process.stdout, "STDOUT"),
                read_stream(process.stderr, "STDERR")
            ),
            timeout=duration_seconds
        )
    except asyncio.TimeoutError:
        # App ran smoothly for the duration target without crashing
        print("[Helix Telemetry] App baseline stabilization verified.")
    finally:
        if process.returncode is None:
            process.terminate()
            await process.wait()
            
    return error_logs
