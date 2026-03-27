/* df-storyteller frontend */

async function switchWorld(world) {
    await fetch('/api/worlds/switch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ world: world })
    });
    window.location.reload();
}
