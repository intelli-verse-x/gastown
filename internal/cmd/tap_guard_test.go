package cmd

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestTapGuardPRWorkflowAllowsAgentWithForkRemote(t *testing.T) {
	dir := initTapGuardGitRepo(t, "https://github.com/example/upstream.git")
	runGit(t, dir, "remote", "add", "fork", "https://github.com/example/fork.git")
	withTapGuardCwd(t, dir)
	t.Setenv("GT_POLECAT", "toast")

	if err := runTapGuardPRWorkflow(nil, nil); err != nil {
		t.Fatalf("runTapGuardPRWorkflow() = %v, want allowed", err)
	}
}

func TestTapGuardPRWorkflowBlocksAgentWithoutForkRemote(t *testing.T) {
	dir := initTapGuardGitRepo(t, "https://github.com/example/upstream.git")
	withTapGuardCwd(t, dir)
	t.Setenv("GT_POLECAT", "toast")

	if err := runTapGuardPRWorkflow(nil, nil); err == nil {
		t.Fatal("runTapGuardPRWorkflow() = nil, want block without fork/upstream workflow")
	}
}

func TestTapGuardPRWorkflowAllowsHumanWithoutForkRemote(t *testing.T) {
	dir := initTapGuardGitRepo(t, "https://github.com/example/upstream.git")
	withTapGuardCwd(t, dir)
	clearTapGuardAgentEnv(t)

	if err := runTapGuardPRWorkflow(nil, nil); err != nil {
		t.Fatalf("runTapGuardPRWorkflow() = %v, want allowed outside agent context", err)
	}
}

func TestTapGuardPRWorkflowAllowsSplitOriginPushURL(t *testing.T) {
	dir := initTapGuardGitRepo(t, "https://github.com/example/upstream.git")
	runGit(t, dir, "remote", "set-url", "--push", "origin", "https://github.com/example/fork.git")
	withTapGuardCwd(t, dir)
	t.Setenv("GT_POLECAT", "toast")

	if err := runTapGuardPRWorkflow(nil, nil); err != nil {
		t.Fatalf("runTapGuardPRWorkflow() = %v, want allowed with split pushurl", err)
	}
}

func TestTapGuardPRWorkflowAllowsUpstreamRemote(t *testing.T) {
	dir := initTapGuardGitRepo(t, "https://github.com/example/fork.git")
	runGit(t, dir, "remote", "add", "upstream", "https://github.com/example/upstream.git")
	withTapGuardCwd(t, dir)
	t.Setenv("GT_POLECAT", "toast")

	if err := runTapGuardPRWorkflow(nil, nil); err != nil {
		t.Fatalf("runTapGuardPRWorkflow() = %v, want allowed with upstream remote", err)
	}
}

func initTapGuardGitRepo(t *testing.T, origin string) string {
	t.Helper()
	dir := t.TempDir()
	runGit(t, dir, "init")
	runGit(t, dir, "remote", "add", "origin", origin)
	return dir
}

func runGit(t *testing.T, dir string, args ...string) {
	t.Helper()
	cmd := exec.Command("git", args...)
	cmd.Dir = dir
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("git %v failed: %v\n%s", args, err, out)
	}
}

func withTapGuardCwd(t *testing.T, dir string) {
	t.Helper()
	old, err := os.Getwd()
	if err != nil {
		t.Fatalf("getwd: %v", err)
	}
	if err := os.Chdir(filepath.Clean(dir)); err != nil {
		t.Fatalf("chdir: %v", err)
	}
	t.Cleanup(func() {
		_ = os.Chdir(old)
	})
}

func clearTapGuardAgentEnv(t *testing.T) {
	t.Helper()
	for _, env := range []string{"GT_POLECAT", "GT_CREW", "GT_WITNESS", "GT_REFINERY", "GT_MAYOR", "GT_DEACON"} {
		t.Setenv(env, "")
	}
}
