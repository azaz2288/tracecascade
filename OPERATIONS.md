# Operations, security and recovery

## Local security model

TraceCascade is a local/small-team tool, not a hosted multi-tenant service. The review workbench binds only to `127.0.0.1`, uses a random per-process CSRF token, rejects oversized or non-form requests and escapes displayed evidence. Review permissions come from a versioned policy file. Events form an append-only SHA-256 chain; deployments can require HMAC signatures by setting `require_hmac: true` and providing `TRACECASCADE_AUDIT_KEY` out of band.

Keep policy, audit and backup secrets outside Git. File access still follows the current OS user's permissions. A party who controls both the files and the secret can forge history; HMAC is integrity/authenticity checking, not non-repudiation.

## Encrypted backup and recovery

Set `TRACECASCADE_BACKUP_PASSWORD` to at least 12 characters, then run:

```sh
tracecascade backup PROJECT_DIRECTORY --out ../project.tracecascade.enc
tracecascade restore ../project.tracecascade.enc RESTORE_DIRECTORY
```

Backups use a random salt, scrypt (`N=16384,r=8,p=1`) and AES-256-GCM. Passwords are never accepted as command-line arguments. The archive excludes `.git`, build products and bytecode; symbolic links and projects above 100 MB are refused. Restore requires an empty destination, authenticates before writing, rejects traversal paths and caps expansion. Test restoration regularly; losing the password makes the backup unrecoverable.

## Review-log recovery

Restore preflight in v1.0.1 checks original ZIP spelling (not only normalized names), portable path segments, case-insensitive collisions in parents/files, file-as-parent conflicts and special file modes. Envelope field types and salt/nonce lengths are checked; boolean versions are not accepted. Existing empty destinations remain supported but symlink/junction destinations are rejected. Current archive excludes empty directories and filesystem metadata; regular file bytes are the recovery contract. Keep trusted local ancestors and stop concurrent writers. These checks do not eliminate malicious path races, guarantee power-loss durability, or provide an atomic snapshot.

Run `tracecascade verify-review-log LOG --policy POLICY` before applying decisions. If verification fails, preserve the damaged log for investigation and restore a known-good encrypted backup. Do not delete or rewrite individual lines because that invalidates the chain. A rejected edge is omitted only in a newly generated reviewed graph; the original graph is never mutated.

## Scale benchmark

Run `python -m benchmarks.scale --nodes 10000`. The default fan-out topology measures broad impact propagation; on the release machine it affected 9,999 nodes in 0.924 seconds with a 13,649,246-byte peak traced Python allocation. Treat that number as a reproducible observation, not a universal guarantee.

Use `--topology chain` to stress deep evidence paths. Reports deliberately repeat each full evidence path, so a chain produces quadratic output volume; 1,000 nodes took 5.833 seconds and 233,143,644 peak traced bytes on the release machine. Dense graphs can also have many competing candidates. Choose production limits using representative topology and required report depth rather than the fan-out number alone.
