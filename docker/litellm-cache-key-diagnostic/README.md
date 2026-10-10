# Bounded cache-key diagnostic overlay

This overlay starts from the immutable d544 image and replaces only the
imported `litellm/caching/caching.py` file with the SHA256-recorded diagnostic
variant. The base file hash is recorded in `SHA256SUMS`. The diagnostic is
disabled by default and must be enabled only for the approved Paperless
`paperless-gpt` to `ha-local` canary. It emits fixed field names, redacted
hashes, a scope-match boolean, and a hashed call correlation; it never emits
messages, credentials, headers, or arbitrary kwargs.

`base-d544-1227bd.caching.py` is the extracted, read-only provenance fixture;
`diagnostic.patch` is the reproducible unified diff applied to that file. The
overlay retains the original cache-key return path and changes only diagnostic
emission around the computed key.
