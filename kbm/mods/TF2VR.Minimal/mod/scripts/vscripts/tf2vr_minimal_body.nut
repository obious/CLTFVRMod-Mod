global function TF2VR_UpdateBodyMovement

// The plugin calls this every frame so its body model follows the player's movement state.
void function TF2VR_UpdateBodyMovement()
{
	entity localPlayer = GetLocalClientPlayer()
	bool inAir = !localPlayer.IsOnGround()
	bool lowered = localPlayer.IsCrouched() || localPlayer.IsSliding()
	TF2VR_SetBodyMovement( inAir, lowered )
}
