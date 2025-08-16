# main.py
# The core analysis engine for the AI Code Integrity Platform MVP.

import ast
import os
import argparse
import requests
import json
import builtins

class CodebaseIndexer(ast.NodeVisitor):
    """
    Traverses an Abstract Syntax Tree (AST) to find all function, class,
    and variable names, creating an index of valid objects in the codebase.
    """
    def __init__(self):
        self.defined_names = set()

    def visit_FunctionDef(self, node):
        self.defined_names.add(node.name)
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        self.defined_names.add(node.name)
        self.generic_visit(node)

    def visit_Assign(self, node):
        for target in node.targets:
            if isinstance(target, ast.Name):
                self.defined_names.add(target.id)
        self.generic_visit(node)

class HallucinationDetector(ast.NodeVisitor):
    """
    Traverses an AST of a changed file and checks all function calls
    and variable uses against the codebase index.
    """
    def __init__(self, codebase_index):
        self.codebase_index = codebase_index
        self.hallucinations = []
        # Create a set of built-in names for efficient lookup
        self.builtins = set(dir(builtins))

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name):
            if node.func.id not in self.codebase_index and node.func.id not in self.builtins:
                self.hallucinations.append({
                    "line": node.lineno,
                    "name": node.func.id,
                    "type": "Function Call"
                })
        self.generic_visit(node)

    def visit_Name(self, node):
        # We only care about variables being loaded/used, not stored/defined.
        if isinstance(node.ctx, ast.Load):
            if node.id not in self.codebase_index:
                # Check against the cached set of built-in functions
                if node.id not in self.builtins:
                    self.hallucinations.append({
                        "line": node.lineno,
                        "name": node.id,
                        "type": "Variable/Object"
                    })
        self.generic_visit(node)

def index_directory(path):
    """
    Walks through a directory, parses all Python files, and returns a
    set of all defined names (functions, classes, variables).
    """
    indexer = CodebaseIndexer()
    for root, _, files in os.walk(path):
        for file in files:
            if file.endswith(".py"):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                        tree = ast.parse(content, filename=file_path)
                        indexer.visit(tree)
                except (SyntaxError, UnicodeDecodeError) as e:
                    print(f"Warning: Could not parse {file_path}. Error: {e}")
    return indexer.defined_names

def analyze_file(file_path, codebase_index):
    """
    Analyzes a single Python file for hallucinations against the codebase index.
    """
    detector = HallucinationDetector(codebase_index)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            tree = ast.parse(content, filename=file_path)
            detector.visit(tree)
    except (SyntaxError, UnicodeDecodeError) as e:
        print(f"Warning: Could not analyze {file_path}. Error: {e}")
    return detector.hallucinations

def post_github_comment(repo, pr_number, token, comment_body):
    """
    Posts a comment to a GitHub Pull Request.
    """
    url = f"https://api.github.com/repos/{repo}/issues/{pr_number}/comments"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    data = {"body": comment_body}
    response = requests.post(url, headers=headers, data=json.dumps(data))
    if response.status_code == 201:
        print("Successfully posted comment to GitHub.")
    else:
        print(f"Failed to post comment. Status: {response.status_code}, Response: {response.text}")

def main():
    parser = argparse.ArgumentParser(description="AI Code Integrity Platform - Hallucination Detector")
    parser.add_argument("--repo_path", required=True, help="Path to the code repository.")
    parser.add_argument("--changed_files", required=True, help="Comma-separated list of changed files to analyze.")
    
    # Arguments for GitHub integration
    parser.add_argument("--github_repo", help="GitHub repository (e.g., 'owner/repo').")
    parser.add_argument("--pr_number", help="Pull Request number.")
    parser.add_argument("--github_token", help="GitHub token for authentication.")

    args = parser.parse_args()

    print("Phase 1: Indexing codebase...")
    codebase_index = index_directory(args.repo_path)
    print(f"Indexed {len(codebase_index)} objects.")

    all_hallucinations = []
    changed_files_list = args.changed_files.split(',')

    print("\nPhase 2: Analyzing changed files...")
    for file_path in changed_files_list:
        stripped_path = file_path.strip()
        if stripped_path.endswith(".py"):
            print(f"Analyzing {stripped_path}...")
            full_path = os.path.join(args.repo_path, stripped_path)
            hallucinations = analyze_file(full_path, codebase_index)
            if hallucinations:
                # Add the file path to each hallucination dictionary
                for h in hallucinations:
                    h_with_file = h.copy()
                    h_with_file['file'] = stripped_path
                    all_hallucinations.append(h_with_file)

    if all_hallucinations:
        print("\nFound potential hallucinations:")
        comment = "### 🤖 AI Code Integrity Check\n\nFound potential 'Hallucinated Objects'. These are references to functions, classes, or variables that could not be found in the current codebase. Please verify them:\n\n"
        for h in all_hallucinations:
            line_entry = "- **File**: `{file}` (Line {line})\n  - **Object**: `{name}` ({type})\n".format(
                file=h['file'], line=h['line'], name=h['name'], type=h['type']
            )
            print(line_entry)
            comment += line_entry
        
        if args.github_repo and args.pr_number and args.github_token:
            post_github_comment(args.github_repo, args.pr_number, args.github_token, comment)
    else:
        print("\nNo hallucinations found. Code looks clean!")

if __name__ == "__main__":
    main()
# This is a test to trigger the hallucination detector
this_is_a_fake_function_that_does_not_exist()

