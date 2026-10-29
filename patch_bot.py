with open('my_bot_v5_candidate.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
skip = False
for line in lines:
    if '# Dynamic capacity threshold tuned from lambda' in line:
        skip = True
        new_lines.append('        if carrying >= capacity * 0.95:\n')
        new_lines.append('            return True\n\n')
        new_lines.append('        if best_drop_utility <= 0.0:\n')
        new_lines.append('            return True\n\n')
        new_lines.append('        v_bank_now = carrying * math.exp(-avg_lambda * hops_to_safe)\n')
        new_lines.append('        rate_bank_now = v_bank_now / max(1, hops_to_safe + 1)\n')
        new_lines.append('        if rate_bank_now > best_drop_utility:\n')
        new_lines.append('            return True\n\n')
        new_lines.append('        return False\n')
        continue
    if skip:
        if 'def decide(' in line:
            skip = False
            new_lines.append('\n' + line)
        continue
    new_lines.append(line)

with open('my_bot_v5_candidate.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
print('Patched successfully!')
