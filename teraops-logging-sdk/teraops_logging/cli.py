"""
TeraOps CLI — teraops init

Copies SDK files into customer's project directory
and shows setup instructions.
"""
import os
import sys
import shutil


def main():
    if len(sys.argv) < 2 or sys.argv[1] != "init":
        print("Usage: teraops init")
        print("  Copies TeraOps SDK files into your project directory.")
        sys.exit(1)

    project_dir = os.getcwd()
    target_dir = os.path.join(project_dir, "teraops_logging")

    # Check if already exists
    if os.path.exists(target_dir):
        print("teraops_logging/ already exists in this directory.")
        print("Remove it first if you want to reinitialize.")
        sys.exit(1)

    # Copy SDK files from installed package to project directory
    source_dir = os.path.dirname(os.path.abspath(__file__))
    shutil.copytree(source_dir, target_dir)

    # Remove cli.py and __pycache__ from the copied files (customer doesn't need these)
    cli_file = os.path.join(target_dir, "cli.py")
    if os.path.exists(cli_file):
        os.remove(cli_file)
    cache_dir = os.path.join(target_dir, "__pycache__")
    if os.path.exists(cache_dir):
        shutil.rmtree(cache_dir)

    # Create .env.example
    env_example = os.path.join(project_dir, ".env.example")
    if not os.path.exists(env_example):
        with open(env_example, "w") as f:
            f.write("TERAOPS_API_URL=your_teraops_api_url_here\n")
            f.write("TERAOPS_API_KEY=your_teraops_api_key_here\n")

    print()
    print("  TeraOps SDK initialized successfully!")
    print()
    print("  Created:")
    print(f"    teraops_logging/     — SDK files")
    print(f"    .env.example         — add your API URL and key here")
    print()
    print("  -----------------------------------------------")
    print("  Now add this to your otel_config.py:")
    print("  -----------------------------------------------")
    print()
    print("  # Add these imports at the top:")
    print("  import os")
    print("  from dotenv import load_dotenv")
    print("  from teraops_logging import attach_teraops")
    print()
    print("  # Add this after your imports:")
    print("  load_dotenv()")
    print()
    print("  # Add this after your LoggerProvider setup:")
    print("  attach_teraops(")
    print('      logger_provider,')
    print('      api_url=os.getenv("TERAOPS_API_URL"),')
    print('      api_key=os.getenv("TERAOPS_API_KEY"),')
    print("  )")
    print()
    print("  -----------------------------------------------")
    print("  Don't forget:")
    print("  -----------------------------------------------")
    print("  1. Copy .env.example to .env")
    print("  2. Fill in your TERAOPS_API_URL and TERAOPS_API_KEY")
    print("     (provided by TeraOps on signup)")
    print("  3. pip install python-dotenv (if not already installed)")
    print()


if __name__ == "__main__":
    main()
