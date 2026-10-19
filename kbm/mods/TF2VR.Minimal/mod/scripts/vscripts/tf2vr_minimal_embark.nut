global function TF2VR_UpdateEmbark

// The plugin calls this while the player climbs into a titan, to place the camera along the embark.
void function TF2VR_UpdateEmbark()
{
	entity localPlayer = GetLocalClientPlayer()
	entity titan = localPlayer.GetParent()
	int hatch = titan.LookupAttachment( "HIJACK" )
	TF2VR_SetEmbarkPose( titan.GetOrigin(), titan.GetAngles().y, titan.GetAttachmentOrigin( hatch ), localPlayer.GetCycle() )
}
