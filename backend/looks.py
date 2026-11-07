"""Character looks: a base Gemini voice + a spoken performance instruction ("Say in a deep, growling monster voice: ...").
Gemini has only 30 prebuilt voices; the instruction is what makes a baby, monster, animal... Samples are made once by
`python generate_look_samples.py` into look_samples/<id>.wav (about 1 TTS request each)."""
LOOK_SAMPLE_TEXT = "ဒီနေရာကို မင်းတို့ ဘယ်သူမှ ထွက်သွားလို့ မရတော့ဘူး။"
# (id, group, label, base voice, instruction)
LOOKS = [
    ("baby", "age", "Baby", "Leda", "Say in the high, cute voice of a small baby-like child"),
    ("child_boy", "age", "Little boy", "Puck", "Say in the bright, excited voice of a young boy of about 7"),
    ("child_girl", "age", "Little girl", "Aoede", "Say in the sweet, high voice of a young girl of about 7"),
    ("teen_boy", "age", "Teen boy", "Fenrir", "Say in the cracking, restless voice of a teenage boy"),
    ("teen_girl", "age", "Teen girl", "Zephyr", "Say in the lively, slightly sulky voice of a teenage girl"),
    ("old_man", "age", "Old man", "Algenib", "Say in the weak, shaky, hoarse voice of a very old man"),
    ("old_woman", "age", "Old woman", "Gacrux", "Say in the thin, trembling voice of a very old woman"),
    ("wise_elder", "age", "Wise elder", "Charon", "Say slowly, in the calm, deep voice of a wise old master"),
    ("monster", "creature", "Monster", "Charon", "Say in a deep, growling, inhuman monster voice"),
    ("giant", "creature", "Giant", "Rasalgethi", "Say in a huge, slow, rumbling voice of a giant"),
    ("demon", "creature", "Demon", "Umbriel", "Say in a low, hissing, menacing demon voice"),
    ("dragon", "creature", "Dragon", "Algieba", "Say in a vast, proud, smoky voice of an ancient dragon"),
    ("goblin", "creature", "Goblin", "Zubenelgenubi", "Say in a cackling, squeaky, sneaky goblin voice"),
    ("zombie", "creature", "Zombie", "Iapetus", "Say in a slow, groaning, dragging zombie voice"),
    ("ghost", "creature", "Ghost", "Vindemiatrix", "Say in an eerie, hollow, whispering ghost voice"),
    ("witch", "creature", "Witch", "Gacrux", "Say in a cackling, raspy old witch voice"),
    ("fairy", "creature", "Fairy", "Laomedeia", "Say in a tiny, tinkling, magical fairy voice"),
    ("alien", "machine", "Alien", "Puck", "Say in a strange, robotic, otherworldly alien voice"),
    ("robot", "machine", "Robot", "Orus", "Say in a flat, metallic robot voice"),
    ("ai", "machine", "AI assistant", "Kore", "Say in a calm, smooth, emotionless artificial intelligence voice"),
    ("cat", "animal", "Talking cat", "Autonoe", "Say like a haughty, purring talking cat"),
    ("dog", "animal", "Talking dog", "Achird", "Say like an eager, panting, friendly talking dog"),
    ("small_animal", "animal", "Small animal", "Zubenelgenubi", "Say like a small talking animal, squeaky and playful"),
    ("bird", "animal", "Bird", "Sadachbia", "Say like a chirpy, fast-talking little bird"),
    ("fox", "animal", "Sly fox", "Algenib", "Say like a sly, smooth, scheming fox"),
    ("bear", "animal", "Bear", "Rasalgethi", "Say like a big, gruff, slow-talking bear"),
    ("villain", "mood", "Villain", "Enceladus", "Say in a cold, quiet, menacing villain voice"),
    ("hero", "mood", "Hero", "Orus", "Say in a brave, firm, heroic voice"),
    ("whisper", "mood", "Whisperer", "Sulafat", "Say in a close, breathy whisper"),
    ("drunk", "mood", "Drunk", "Schedar", "Say in a slurred, rambling drunk voice"),
    ("sleepy", "mood", "Sleepy", "Achernar", "Say in a slow, yawning, half-asleep voice"),
    ("announcer", "mood", "Announcer", "Alnilam", "Say like a loud, dramatic movie-trailer announcer"),
]
LOOK_IDS = {l[0] for l in LOOKS}
