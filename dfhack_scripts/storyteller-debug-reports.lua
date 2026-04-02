-- Debug: log ALL recent reports with their types to find combat report gaps
-- Run this DURING or RIGHT AFTER a fight to see what report types were generated
if df.global.gamemode ~= df.game_mode.DWARF then print('Not in fortress mode'); return end

local reports = df.global.world.status.reports
print('Total reports in buffer: ' .. #reports)
print()

-- Show the last 50 reports
local start = math.max(0, #reports - 50)
print('Last ' .. (#reports - start) .. ' reports:')
for i = start, #reports - 1 do
    local r = reports[i]
    local text = r.text or ''
    pcall(function() text = dfhack.df2utf(text) end)
    local rtype = r.type or -1

    -- Check if this type falls in our combat ranges
    local is_combat = (rtype >= 6 and rtype <= 48)
        or (rtype >= 111 and rtype <= 134)
        or rtype == 166 or rtype == 167
        or rtype == 239 or rtype == 171
    local tag = is_combat and ' [COMBAT]' or ''

    -- Check if it's a known skip type
    local skip_types = {[104]=true,[236]=true,[237]=true,[278]=true,[282]=true,[283]=true,[297]=true,[298]=true,[299]=true,[300]=true,[342]=true}
    if skip_types[rtype] then tag = ' [SKIP]' end

    print(string.format('  [%d] type=%d%s: %s', r.id, rtype, tag, text:sub(1, 120)))
end

-- Also check: what types exist that are NOT in our combat range but contain combat-like text?
print()
print('Reports with combat-like text but NOT tagged as combat:')
for i = start, #reports - 1 do
    local r = reports[i]
    local text = (r.text or ''):lower()
    local rtype = r.type or -1
    local is_combat = (rtype >= 6 and rtype <= 48)
        or (rtype >= 111 and rtype <= 134)
        or rtype == 166 or rtype == 167
        or rtype == 239 or rtype == 171
    if not is_combat and (
        text:find('strikes') or text:find('bites') or text:find('kicks') or
        text:find('scratches') or text:find('punches') or text:find('misses') or
        text:find('grabs') or text:find('tearing') or text:find('bruising') or
        text:find('attack') or text:find('latches') or text:find('slams')
    ) then
        pcall(function() text = dfhack.df2utf(r.text) end)
        print(string.format('  type=%d: %s', rtype, text:sub(1, 150)))
    end
end

print('Done.')
