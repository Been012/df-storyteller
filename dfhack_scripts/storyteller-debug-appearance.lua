-- Test: trigger DF screenshot via key simulation
-- OPEN A DWARF INFO PANEL before running!

if df.global.gamemode ~= df.game_mode.DWARF then print('Not in fortress mode'); return end

-- Check what screenshot files exist before
local df_path = dfhack.getDFPath()
print('DF path: ' .. df_path)
print('')

-- List existing screenshot files
print('Existing screenshots:')
local files = dfhack.filesystem.listdir(df_path)
for _, f in ipairs(files) do
    if string.find(f, 'screenshot') or string.find(f, '.bmp') or string.find(f, '.png') then
        print('  ' .. f)
    end
end

-- Try to trigger a screenshot
print('')
print('Triggering screenshot...')

-- Method 1: Use gui.simulateInput with the screenshot key
pcall(function()
    local gui = require('gui')
    -- DF screenshot key is typically SCREENSHOT
    local scr = dfhack.gui.getCurViewscreen()
    if scr then
        print('  Current viewscreen: ' .. tostring(scr._type))
        -- Try feeding SCREENSHOT key
        gui.simulateInput(scr, 'SCREENSHOT')
        print('  Sent SCREENSHOT input')
    end
end)

-- Wait a moment then check for new files
print('')
print('Checking for new screenshot files...')
dfhack.timeout(30, 'frames', function()
    local files2 = dfhack.filesystem.listdir(df_path)
    for _, f in ipairs(files2) do
        if string.find(f, 'screenshot') or string.find(f, '.bmp') or string.find(f, '.png') then
            print('  Found: ' .. f)
        end
    end
    print('Done checking')
end)
