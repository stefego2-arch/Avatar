from md_library import load_md_chunks

path = "manuale/Matematica_1106.md"
chunks = load_md_chunks(path)

print("chunks:", len(chunks))
i = 0

while True:
    print("\n" + "="*80)
    print(f"CHUNK {i+1}/{len(chunks)}\n")
    print(chunks[i][:900])
    cmd = input("\n[n]ext, [p]rev, [q]uit > ").strip().lower()
    if cmd == "n":
        i = min(len(chunks)-1, i+1)
    elif cmd == "p":
        i = max(0, i-1)
    elif cmd == "q":
        break
