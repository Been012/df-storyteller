-- Debug: try to resolve pcg_layering via PCGLayeringType enum
if df.global.gamemode ~= df.game_mode.DWARF then print('Not in fortress mode'); return end

-- Check if the enum exists
print('=== PCGLayeringType enum ===')
pcall(function()
    local enum = df.PCGLayeringType
    if not enum then print('NOT FOUND'); return end

    -- Try to resolve known pcg values
    local test_values = {17, 24, 118, 139, 933, 1066, 1092, 1144, 1149, 1623}
    for _, pcg in ipairs(test_values) do
        local name = '?'
        pcall(function() name = tostring(enum[pcg]) end)
        print('  pcg ' .. pcg .. ' = ' .. name)
    end

    -- Count total enum values
    pcall(function()
        local count = 0
        for i = 0, 3000 do
            local n = enum[i]
            if n and n ~= 'anon_1' then count = i end
        end
        print('  Max enum value: ~' .. count)
    end)
end)

-- Also try alternate names
pcall(function()
    local enum = df.pcg_layering_type
    if enum then
        print('Found as df.pcg_layering_type!')
        print('  [17] = ' .. tostring(enum[17]))
    end
end)

pcall(function()
    local enum = df.creature_graphics_pcg_layering
    if enum then
        print('Found as df.creature_graphics_pcg_layering!')
    end
end)

print('Done.')
