global function TF2VR_RecenterCommand
global function TF2VR_SwitchEyeCommand
global function TF2VR_ToggleBarfCommand

// console commands (mod.json ConCommands), meant for key binds; the launcher can bind them. Northstar calls these
// with no arguments

// tf2vr_recenter: the same recenter as the pause menu button, which also opens and closes a menu; while a menu is up
// the plugin re-aligns the body with the head, so ask its view code for that for a moment (tf2vr_realign_body,
// read by the keyboard and mouse patch) without showing a menu
void function TF2VR_RecenterCommand()
{
	TF2VR_RequestRecenter()
	thread TF2VR_RealignBody()
}

void function TF2VR_RealignBody()
{
	SetConVarBool( "tf2vr_realign_body", true )
	wait 0.3
	SetConVarBool( "tf2vr_realign_body", false )
}

// tf2vr_switch_eye: sights line up with the other eye (between the eyes switches to left)
void function TF2VR_SwitchEyeCommand()
{
	SetConVarFloat( "tf2vr_ads_eye", GetConVarFloat( "tf2vr_ads_eye" ) < 0 ? 1.0 : -1.0 )
	printt( "tf2vr_ads_eye " + GetConVarFloat( "tf2vr_ads_eye" ) )
}

// tf2vr_toggle_barf: mouse up/down tilting the VR view on or off for this session (the launcher sets it each launch)
void function TF2VR_ToggleBarfCommand()
{
	SetConVarFloat( "tf2vr_barf_mode", GetConVarFloat( "tf2vr_barf_mode" ) > 0 ? 0.0 : 1.0 )
	printt( "tf2vr_barf_mode " + GetConVarFloat( "tf2vr_barf_mode" ) )
}

