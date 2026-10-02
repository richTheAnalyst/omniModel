with open('C:/laravelapps/omniModel/streamlit_app.py', 'r') as f:
    content = f.read()

lines = content.split('\n')

tab_analyze_idx = None
tab_wide_idx = None
for i, line in enumerate(lines):
    if 'with tab_analyze:' in line:
        tab_analyze_idx = i
    if 'with tab_wide:' in line:
        tab_wide_idx = i
        break

before = lines[:tab_analyze_idx]
after = lines[tab_wide_idx:]
tab_content = lines[tab_analyze_idx+1:tab_wide_idx]

fixed_tab = []
for line in tab_content:
    stripped = line.strip()
    if not stripped:
        fixed_tab.append('')
        continue
    if stripped.startswith('with ') or stripped.startswith('if ') or stripped.startswith('for ') or stripped.startswith('tp,') or stripped.startswith('te,') or stripped.startswith('tf,'):
        fixed_tab.append('    ' + stripped)
    elif stripped.startswith('with col_') or stripped.startswith('with tp') or stripped.startswith('with te') or stripped.startswith('with tf') or stripped.startswith('with col_pdf') or stripped.startswith('with col_docx') or stripped.startswith('with col_txt') or stripped.startswith('with col_g') or stripped.startswith('with col_b') or stripped.startswith('with col_d') or stripped.startswith('with col_o') or stripped.startswith('with col_clear') or stripped.startswith('with col_analyze') or stripped.startswith('with col_batch') or stripped.startswith('with col_exp') or stripped.startswith('with col_max') or stripped.startswith('with col_run') or stripped.startswith('with col_country') or stripped.startswith('with col_area') or stripped.startswith('with col_city') or stripped.startswith('with col_query') or stripped.startswith('with status') or stripped.startswith('with st.status') or stripped.startswith('try:') or stripped.startswith('except'):
        fixed_tab.append('        ' + stripped)
    else:
        fixed_tab.append('    ' + stripped)

new_content = '\n'.join(before) + '\n' + '\n'.join(fixed_tab) + '\n' + '\n'.join(after)
with open('C:/laravelapps/omniModel/streamlit_app.py', 'w') as f:
    f.write(new_content)
print('File rewritten')