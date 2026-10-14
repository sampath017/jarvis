/// Coalesce syncs while ensuring a requested pull follows an in-flight push.
class SyncCoordinator {
  SyncCoordinator(this.perform);

  final Future<void> Function(bool pullRemote) perform;
  Future<void>? _active;
  bool _activePull = false;

  Future<void> run({bool pullRemote = true}) {
    final active = _active;
    if (active != null) {
      if (pullRemote && !_activePull) {
        return active.then((_) => run());
      }
      return active;
    }
    _activePull = pullRemote;
    return _active = Future<void>.sync(
      () => perform(pullRemote),
    ).whenComplete(() => _active = null);
  }
}
