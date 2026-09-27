import subprocess

def ask_chatgpt(prompt):
    result = subprocess.run(
        [
            "codex",
            "exec",
            "-m", "gpt-5.6-luna",
            "-c", 'model_reasoning_effort="low"',
            "--skip-git-repo-check",
            prompt
        ],
        capture_output=True,
        text=True
    )

    return result.stdout.strip()


answer = ask_chatgpt("hi")
print(answer)