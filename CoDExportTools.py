# Copyright 2014, Aidan Shafran

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


#	Changed XMODEL_FORMAT to CoD1/UO
#	riicchhaarrd

# VERSION INFO
# VERSION 1
#	+ Original - XModel Exporter, XAnim Exporter, and ViewModel tools
# VERSION 1.1
#	+ Added feature to switch the gun in a weapon rig file
#	* Fixed trying to write to the export file before it was created
#	* Changed the "No joints selected; exporting with a default TAG_ORIGIN." warning to not create a warning dialog after export
#	* Other small random fixes
# VERSION 1.2
#	+ Added button to export multiple models/animations at once
#	* Moved some of the user-changeable variables in the script to the top of the file in the CUSTOMIZATION section
# VERSION 1.3
#	* Fixed excessive TRI_VERT_RATIO error (this can still happen if something is wrong with your model, but this update should help)
# VERSION 1.4
#	* Changed new version message to open website forum topic instead of message box
#	* Fixed model without skin exporting in Object space instead of World space

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------
# ---------------------------------------------------------- CUSTOMIZATION (You can change these values!) ----------------------------------------------------------
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------
MAX_WARNINGS_SHOWN = 100 # Maximum number of warnings to show per export
EXPORT_WINDOW_NUMSLOTS = 10 # Number of slots in the export windows



# ------------------------------------------------------------------------------------------------------------------------------------------------------------------
# ---------------------------------------------------------------------------- GLOBAL ------------------------------------------------------------------------------
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------
import os
import maya.cmds as cmds
import maya.mel as mel
import math
import sys
import datetime
import os.path
import traceback
import maya.OpenMaya as OpenMaya
import maya.OpenMayaAnim as OpenMayaAnim
from urllib import error as urllib_error
from urllib import request as urllib_request
import socket
import webbrowser
import queue
import winreg as reg
import time

WarningsDuringExport = 0 # Number of warnings shown during current export
CM_TO_INCH = 0.3937007874015748031496062992126 # 1cm = 50/127in
FILE_VERSION = 1.4 # Can be decimal
GLOBAL_STORAGE_REG_KEY = (reg.HKEY_CURRENT_USER, "Software\\CoDMayaExportTools") # Registry path for global data storage
#				name	 : control code name,	control friendly name,	data storage node name,	refresh function,		export function
OBJECT_NAMES = 	{'menu'  : ["CoD5ToolsMenu",    "Call of Duty 1 Tools", None,					None,					None],
				 'progress' : ["CoDExportToolsProgressbar", "Export Progress", None,			None,					None],
				 'xmodel': ["CoD5XModelWindow", "Export XModel",		"XModelExporterInfo",	"RefreshXModelWindow",	"ExportXModel"],
				 'xanim' : ["CoD5XAnimWindow",  "Export XAnim",			"XAnimExporterInfo",	"RefreshXAnimWindow",	"ExportXAnim"]}



# ------------------------------------------------------------------------------------------------------------------------------------------------------------------				
# ------------------------------------------------------------------- JOINTS (XModel and XAnim) --------------------------------------------------------------------
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------
def GetJointList():
	joints = []
	
	# Get selected objects
	selectedObjects = OpenMaya.MSelectionList()
	OpenMaya.MGlobal.getActiveSelectionList(selectedObjects)
	
	for i in range(selectedObjects.length()):
		# Some Maya 2022 selections are components or non-DAG items.
		# Skip those instead of hard-failing the whole export.
		dagPath = OpenMaya.MDagPath()
		try:
			selectedObjects.getDagPath(i, dagPath)
		except RuntimeError:
			ProgressBarStep()
			continue
		
		dagNode = OpenMaya.MFnDagNode(dagPath)
		
		# Ignore nodes that aren't joints or arn't top-level
		if not dagPath.hasFn(OpenMaya.MFn.kJoint) or not RecursiveCheckIsTopNode(selectedObjects, dagNode):
			ProgressBarStep()
			continue
		
		# Breadth first search of joint tree
		searchQueue = queue.Queue(0)
		searchQueue.put((-1, dagNode, True)) # (index = child node's parent index, child node)
		while not searchQueue.empty():
			node = searchQueue.get()
			index = len(joints)
			
			if node[2]:
				joints.append((node[0], node[1]))
			else:
				index = node[0]
			
			for i in range(node[1].childCount()):
				dagPath = OpenMaya.MDagPath()
				childNode = OpenMaya.MFnDagNode(node[1].child(i))
				childNode.getPath(dagPath)
				searchQueue.put((index, childNode, selectedObjects.hasItem(dagPath) and dagPath.hasFn(OpenMaya.MFn.kJoint)))
		
		ProgressBarStep()
	
	return joints

def RecursiveCheckIsTopNode(cSelectionList, currentNode): # Checks if the given node has ANY selected parent, grandparent, etc joints
	if currentNode.parentCount() == 0:
		return True
	
	for i in range(currentNode.parentCount()):
		parentDagPath = OpenMaya.MDagPath()
		parentNode = OpenMaya.MFnDagNode(currentNode.parent(i))
		parentNode.getPath(parentDagPath)
	
		if not parentDagPath.hasFn(OpenMaya.MFn.kJoint): # Not a joint, but still check parents
			if not RecursiveCheckIsTopNode(cSelectionList, parentNode):
				return False # A parent joint is selected, we're done
			else:
				continue # No parent joints are selected, ignore this node
		
		if cSelectionList.hasItem(parentDagPath):
			return False
		else:
			if not RecursiveCheckIsTopNode(cSelectionList, parentNode):
				return False
				
	return True
	
def WriteJointData(f, jointNode):
	# Get the joint's transform
	path = OpenMaya.MDagPath()
	jointNode.getPath(path)
	transform = OpenMaya.MFnTransform(path)
	
	# Get joint position
	pos = transform.getTranslation(OpenMaya.MSpace.kWorld)
	
	# Get scale (almost always 1)
	scaleUtil = OpenMaya.MScriptUtil()
	scaleUtil.createFromList([1,1,1], 3)
	scalePtr = scaleUtil.asDoublePtr()
	transform.getScale(scalePtr)
	scale = [OpenMaya.MScriptUtil.getDoubleArrayItem(scalePtr, 0), OpenMaya.MScriptUtil.getDoubleArrayItem(scalePtr, 1), OpenMaya.MScriptUtil.getDoubleArrayItem(scalePtr, 2)]
	
	# Get rotation matrix (mat is a 4x4, but the last row and column arn't needed)
	rotQuaternion = OpenMaya.MQuaternion()
	transform.getRotation(rotQuaternion, OpenMaya.MSpace.kWorld)
	mat = rotQuaternion.asMatrix()
	
	# Write
	f.write("OFFSET %f %f %f\n" % (pos.x*CM_TO_INCH, pos.y*CM_TO_INCH, pos.z*CM_TO_INCH))
	f.write("SCALE %f %f %f\n" % (scale[0], scale[1], scale[2]))
	f.write("X %f %f %f\n" % (mat(0,0), mat(0,1), mat(0,2)))
	f.write("Y %f %f %f\n" % (mat(1,0), mat(1,1), mat(1,2)))
	f.write("Z %f %f %f\n" % (mat(2,0), mat(2,1), mat(2,2)))


	
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------				
# ----------------------------------------------------------------------------- XMODELS ----------------------------------------------------------------------------
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------
def CreateXModelWindow():
	# Create window
	if cmds.control(OBJECT_NAMES['xmodel'][0], exists=True):
		cmds.deleteUI(OBJECT_NAMES['xmodel'][0])
	
	cmds.window(OBJECT_NAMES['xmodel'][0], title=OBJECT_NAMES['xmodel'][1], width=340, height=1, retain=True, maximizeButton=False)
	form = cmds.formLayout(OBJECT_NAMES['xmodel'][0]+"_Form")
	
	# Controls
	slotDropDown = cmds.optionMenu(OBJECT_NAMES['xmodel'][0]+"_SlotDropDown", changeCommand="CoDExportTools.RefreshXModelWindow()", annotation="Each slot contains different a export path, settings, and saved selection")
	for i in range(1, EXPORT_WINDOW_NUMSLOTS+1):
		cmds.menuItem(OBJECT_NAMES['xmodel'][0]+"_SlotDropDown"+("_s%i" % i), label="Slot %i" % i)
	
	separator1 = cmds.separator(style='in', height=16)
	separator2 = cmds.separator(style='in')
	
	saveToLabel = cmds.text(label="Save to:", annotation="This is where the .xmodel_export is saved to")
	saveToField = cmds.textField(OBJECT_NAMES['xmodel'][0]+"_SaveToField", height=21, changeCommand="CoDExportTools.GeneralWindow_SaveToField('xmodel')", annotation="This is where the .xmodel_export is saved to")
	fileBrowserButton = cmds.button(label="...", height=21, command="CoDExportTools.GeneralWindow_FileBrowser('xmodel', \"XModel Intermediate File (*.xmodel_export)\")", annotation="Open a file browser dialog")
	
	exportSelectedButton = cmds.button(label="Export Selected", command="CoDExportTools.GeneralWindow_ExportSelected('xmodel', False)", annotation="Export all currently selected objects from the scene (current frame)\nWarning: Will automatically overwrite if the export path if it already exists")
	saveSelectionButton = cmds.button(label="Save Selection", command="CoDExportTools.GeneralWindow_SaveSelection('xmodel')", annotation="Save the current object selection")
	getSavedSelectionButton = cmds.button(label="Get Saved Selection", command="CoDExportTools.GeneralWindow_GetSavedSelection('xmodel')", annotation="Reselect the saved selection")
	
	exportMultipleSlotsButton = cmds.button(label="Export Multiple Slots", command="CoDExportTools.GeneralWindow_ExportMultiple('xmodel')", annotation="Automatically export multiple slots at once, using each slot's saved selection")
	exportInMultiExportCheckbox = cmds.checkBox(OBJECT_NAMES['xmodel'][0]+"_UseInMultiExportCheckBox", label="Use current slot for Export Multiple", changeCommand="CoDExportTools.GeneralWindow_ExportInMultiExport('xmodel')", annotation="Check this make the 'Export Multiple Slots' button export this slot")

	# Setup form
	cmds.formLayout(form, edit=True,
		attachForm=[(slotDropDown, 'top', 6), (slotDropDown, 'left', 10), (slotDropDown, 'right', 10),
					(separator1, 'left', 0), (separator1, 'right', 0),
					(separator2, 'left', 0), (separator2, 'right', 0),
					(saveToLabel, 'left', 12),
					(fileBrowserButton, 'right', 10),
					(exportMultipleSlotsButton, 'bottom', 6), (exportMultipleSlotsButton, 'left', 10),
					(exportInMultiExportCheckbox, 'bottom', 9), (exportInMultiExportCheckbox, 'right', 6),
					(exportSelectedButton, 'left', 10),
					(saveSelectionButton, 'right', 10)],
					#(exportSelectedButton, 'bottom', 6), (exportSelectedButton, 'left', 10),
					#(saveSelectionButton, 'bottom', 6), (saveSelectionButton, 'right', 10),
					#(getSavedSelectionButton, 'bottom', 6)],
		
		attachControl=[	(separator1, 'top', 0, slotDropDown),
						(saveToLabel, 'bottom', 9, exportSelectedButton),
						(saveToField, 'bottom', 5, exportSelectedButton), (saveToField, 'left', 5, saveToLabel), (saveToField, 'right', 5, fileBrowserButton),
						(fileBrowserButton, 'bottom', 5, exportSelectedButton),
						(exportSelectedButton, 'bottom', 5, separator2),
						(saveSelectionButton, 'bottom', 5, separator2),
						(getSavedSelectionButton, 'bottom', 5, separator2), (getSavedSelectionButton, 'right', 10, saveSelectionButton),
						(separator2, 'bottom', 5, exportMultipleSlotsButton)])

def RefreshXModelWindow():
	# Refresh/create node
	if len(cmds.ls(OBJECT_NAMES['xmodel'][2])) == 0:
		cmds.createNode("renderLayer", name=OBJECT_NAMES['xmodel'][2], skipSelect=True)
	
	cmds.lockNode(OBJECT_NAMES['xmodel'][2], lock=False)
	
	if not cmds.attributeQuery("slot", node=OBJECT_NAMES['xmodel'][2], exists=True):
		cmds.addAttr(OBJECT_NAMES['xmodel'][2], longName="slot", attributeType='short', defaultValue=1)
	if not cmds.attributeQuery("paths", node=OBJECT_NAMES['xmodel'][2], exists=True):
		cmds.addAttr(OBJECT_NAMES['xmodel'][2], longName="paths", multi=True, dataType='string')
		cmds.setAttr(OBJECT_NAMES['xmodel'][2]+".paths", size=EXPORT_WINDOW_NUMSLOTS)
	if not cmds.attributeQuery("selections", node=OBJECT_NAMES['xmodel'][2], exists=True):
		cmds.addAttr(OBJECT_NAMES['xmodel'][2], longName="selections", multi=True, dataType='stringArray')
		cmds.setAttr(OBJECT_NAMES['xmodel'][2]+".selections", size=EXPORT_WINDOW_NUMSLOTS)
	if not cmds.attributeQuery("useinmultiexport", node=OBJECT_NAMES['xmodel'][2], exists=True):
		cmds.addAttr(OBJECT_NAMES['xmodel'][2], longName="useinmultiexport", multi=True, attributeType='bool', defaultValue=False)
		cmds.setAttr(OBJECT_NAMES['xmodel'][2]+".useinmultiexport", size=EXPORT_WINDOW_NUMSLOTS)
		
	cmds.lockNode(OBJECT_NAMES['xmodel'][2], lock=True)
	
	# Set values
	slotIndex = cmds.optionMenu(OBJECT_NAMES['xmodel'][0]+"_SlotDropDown", query=True, select=True)
	path = cmds.getAttr(OBJECT_NAMES['xmodel'][2]+(".paths[%i]" % slotIndex))
	cmds.setAttr(OBJECT_NAMES['xmodel'][2]+".slot", slotIndex)
	cmds.textField(OBJECT_NAMES['xmodel'][0]+"_SaveToField", edit=True, fileName=path)

	useInMultiExport = cmds.getAttr(OBJECT_NAMES['xmodel'][2]+(".useinmultiexport[%i]" % slotIndex))
	cmds.checkBox(OBJECT_NAMES['xmodel'][0]+"_UseInMultiExportCheckBox", edit=True, value=useInMultiExport)
	
def ExportXModel(filePath):
	# Progress bar
	numSelectedObjects = len(cmds.ls(selection=True))
	if numSelectedObjects == 0:
		return "Error: No objects selected for export"
		
	cmds.progressBar(OBJECT_NAMES['progress'][0], edit=True, maxValue=numSelectedObjects*2+1)

	# Get data
	joints = GetJointList()
	if len(joints) > 128:
		return "Error: More than 128 joints"
	shapes = GetShapes(joints)
	if type(shapes) == str:
		return shapes
	
	# Open file
	f = None
	try:
		# Create export directory if it doesn't exist
		directory = os.path.dirname(filePath)
		if not os.path.exists(directory):
			os.makedirs(directory)
		
		# Create file
		f = open(filePath, 'w')
	except (IOError, OSError) as e:
		typex, value, traceback = sys.exc_info()
		return "Unable to create file:\n\n%s" % value.strerror
	
	# Write header
	f.write("// Export filename: '%s'\n" % os.path.normpath(filePath))
	if cmds.file(query=True, exists=True):
		f.write("// Source filename: '%s'\n" % os.path.normpath(os.path.abspath(cmds.file(query=True, sceneName=True))))
	else:
		f.write("// Source filename: Unsaved\n")
	f.write("// Export time: %s\n\n" % datetime.datetime.now().strftime("%a %b %d %Y, %H:%M:%S"))
	f.write("MODEL\n")
	f.write("VERSION 5\n\n")
	
	# Write joints
	if len(joints) == 0:
		print("No joints selected; exporting with a default TAG_ORIGIN.")
		f.write("NUMBONES 1\n")
		f.write("BONE 0 -1 \"TAG_ORIGIN\"\n\n")
		
		f.write("BONE 0\n")
		f.write("OFFSET 0.000000 0.000000 0.000000\n")
		f.write("SCALE 1.000000 1.000000 1.000000\n")
		f.write("X 1.000000 0.000000 0.000000\n")
		f.write("Y 0.000000 1.000000 0.000000\n")
		f.write("Z 0.000000 0.000000 1.000000\n")
	else:
		f.write("NUMBONES %i\n" % len(joints))
		for i, joint in enumerate(joints):
			name = joint[1].partialPathName().split("|")
			name = name[len(name)-1].split(":") # Remove namespace prefixes
			name = name[len(name)-1]
			f.write("BONE %i %i \"%s\"\n" % (i, joint[0], name))
		
		for i, joint in enumerate(joints):
			f.write("\nBONE %i\n" % i)
			WriteJointData(f, joint[1])
	
	# Write verts
	f.write("\nNUMVERTS %i\n" % len(shapes["verts"]))
	for i, vert in enumerate(shapes["verts"]):
		f.write("VERT %i\n" % i)
		f.write("OFFSET %f %f %f\n" % (vert[0].x*CM_TO_INCH, vert[0].y*CM_TO_INCH, vert[0].z*CM_TO_INCH)) # Offsets are stored in CM, but cod uses inches
		f.write("BONES %i\n" % max(len(vert[1]), 1))
		if len(vert[1]) > 0:
			for bone in vert[1]:
				f.write("BONE %i %f\n" % (bone[0], bone[1]))
		else:
			f.write("BONE 0 1.000000\n")
		f.write("\n")
	
	# Write faces
	f.write("NUMFACES %i\n" % len(shapes["faces"]))
	for j, face in enumerate(shapes["faces"]):
		f.write("TRI %i %i 0 1\n" % (face[0], face[1]))
		for i in range(0, 3):
			f.write("VERT %i " % face[2][i])
			f.write("%f %f " % (face[3][i][0], face[3][i][1]))
			f.write("%f %f %f\n" % (face[5][i].x, face[5][i].y, face[5][i].z))
		#f.write("")
	
	# Write objects
	f.write("NUMOBJECTS %i\n" % len(shapes["meshes"]))
	for i, object in enumerate(shapes["meshes"]):
		f.write("OBJECT %i \"%s\"\n" % (i, object))
	
	# Write materials
	f.write("\nNUMMATERIALS %i\n" % len(shapes["materials"]))
	for i, material in enumerate(shapes["materials"]):
		f.write("MATERIAL %i \"%s\"\n" % (i, material[0]))
		
		# According to the Modrepository page on the XModel format, the following values don't matter
		
	f.close()
	ProgressBarStep()
	cmds.refresh()

def GetMaterialsFromMesh(mesh, dagPath):
	textures = {}
	
	# Use cmds-based graph lookups here because Maya 2022 is stricter about
	# low-level plug compatibility than the original 2012-era API code.
	shaders = OpenMaya.MObjectArray()
	shaderIndices = OpenMaya.MIntArray()
	mesh.getConnectedShaders(dagPath.instanceNumber(), shaders, shaderIndices)
	
	for i in range(shaders.length()):
		shaderNode = OpenMaya.MFnDependencyNode(shaders[i])
		shadingEngineName = shaderNode.name()
		materialName = shadingEngineName
		texturePath = ""
		
		connectedMaterials = cmds.listConnections(
			shadingEngineName + ".surfaceShader",
			source=True,
			destination=False
		) or []
		if len(connectedMaterials) > 0:
			materialName = connectedMaterials[0]
			for attribute in ("color", "baseColor", "outColor"):
				if not cmds.attributeQuery(attribute, node=materialName, exists=True):
					continue
				fileNodes = cmds.listConnections(
					materialName + "." + attribute,
					source=True,
					destination=False,
					type="file"
				) or []
				if len(fileNodes) > 0:
					filePath = cmds.getAttr(fileNodes[0] + ".fileTextureName") or ""
					texturePath = os.path.basename(filePath)
					break
		
		textures[i] = (materialName, texturePath)
	
	texturesToFaces = []
	for i in range(shaderIndices.length()):
		if shaderIndices[i] in textures:
			texturesToFaces.append(textures[shaderIndices[i]])
		else:
			texturesToFaces.append(None)
	
	return texturesToFaces

# Converts a set of vertices (toConvertVertexIndices) from object-relative IDs to face-relative IDs
# vertexIndices is a list of object-relative vertex indices in face order (from polyIter.getVertices)
# toConvertVertexIndices is any set of vertices from the same faces as vertexIndices, not necessarily the same length
# Returns false if a vertex index is unable to be converted (= bad vertex values)
def VerticesObjRelToLocalRel(vertexIndices, toConvertVertexIndices):
	# http://svn.gna.org/svn/cal3d/trunk/cal3d/plugins/cal3d_maya_exporter/MayaMesh.cpp
	localVertexIndices = OpenMaya.MIntArray()
	
	for i in range(toConvertVertexIndices.length()):
		found = False
		for j in range(vertexIndices.length()):
			if toConvertVertexIndices[i] == vertexIndices[j]:
				localVertexIndices.append(j)
				found = True
				break
		if not found:
			return False
	
	return localVertexIndices
	
def GetShapes(joints):
	# Vars
	meshes = []
	verts = []
	tris = []
	materialDict = {}
	materials = []
	
	# Convert the joints to a dictionary, for simple searching for joint indices
	jointDict = {}
	for i, joint in enumerate(joints):
		jointDict[joint[1].partialPathName()] = i
	
	# Get all selected objects
	selectedObjects = OpenMaya.MSelectionList()
	OpenMaya.MGlobal.getActiveSelectionList(selectedObjects)
	
	# The global vert index at the start of each object
	currentStartingVertIndex = 0
	
	# Loop through all objects
	for i in range(0, selectedObjects.length()):
		# Get data on object
		object = OpenMaya.MObject()
		dagPath = OpenMaya.MDagPath()
		selectedObjects.getDependNode(i, object)
		try:
			selectedObjects.getDagPath(i, dagPath)
		except RuntimeError:
			ProgressBarStep()
			continue
		
		# Selecting a mesh transform should still export its shape in Maya 2022.
		if not dagPath.hasFn(OpenMaya.MFn.kMesh):
			try:
				dagPath.extendToShape()
			except RuntimeError:
				ProgressBarStep()
				continue
		
		# Ignore dag nodes that aren't meshes after resolving transforms/components.
		if not dagPath.hasFn(OpenMaya.MFn.kMesh):
			ProgressBarStep()
			continue
		
		# Check for duplicates
		if dagPath.partialPathName() in meshes:
			ProgressBarStep()
			continue
		
		# Add shape to list
		meshes.append(dagPath.partialPathName())
		
		# Get mesh
		mesh = OpenMaya.MFnMesh(dagPath)
		
		# Get skin cluster
		clusterName = mel.eval("findRelatedSkinCluster " + dagPath.partialPathName()) # I couldn't figure out how to get the skin cluster via the API
		hasSkin = False
		if clusterName != None and clusterName != "" and not clusterName.isspace():
			hasSkin = True
			selList = OpenMaya.MSelectionList()
			selList.add(clusterName)
			clusterNode = OpenMaya.MObject()
			selList.getDependNode(0, clusterNode)
			skin = OpenMayaAnim.MFnSkinCluster(clusterNode)
		
		# Loop through all vertices
		vertIter = OpenMaya.MItMeshVertex(dagPath)
		while not vertIter.isDone():
			if not hasSkin:
				verts.append((vertIter.position(OpenMaya.MSpace.kWorld), []))
				vertIter.next()
				continue
			
			# Get weight values
			weightValues = OpenMaya.MDoubleArray()
			numWeights = OpenMaya.MScriptUtil() # Need this because getWeights crashes without being passed a count
			skin.getWeights(dagPath, vertIter.currentItem(), weightValues, numWeights.asUintPtr())
			
			# Get weight names
			weightJoints = OpenMaya.MDagPathArray()
			skin.influenceObjects(weightJoints)
			
			# Make sure the list of weight values and names match
			if weightValues.length() != weightJoints.length():
				PrintWarning("Failed to retrieve vertex weight list on '%s.vtx[%d]'; using default joints." % (dagPath.partialPathName(), vertIter.index()))
			
			# Remove weights of value 0 or weights from unexported joints
			finalWeights = []
			weightsSize = 0
			for i in range(0, weightJoints.length()):
				if weightValues[i] < 0.000001: # 0.000001 is the smallest decimal in xmodel exports
					continue
				jointName = weightJoints[i].partialPathName()
				if not jointName in jointDict:
					PrintWarning("Unexported joint %s is influencing vertex '%s.vtx[%d]' by %f%%" % (("'%s'" % jointName).ljust(15), dagPath.partialPathName(), vertIter.index(), weightValues[i]*100))
				else:
					finalWeights.append([jointDict[jointName], weightValues[i]])
					weightsSize += weightValues[i]
			
			# Make sure the total weight adds up to 1
			if weightsSize > 0:
				weightMultiplier = 1 / weightsSize
				for weight in finalWeights:
					weight[1] *= weightMultiplier
			
			verts.append((
				vertIter.position(OpenMaya.MSpace.kWorld), # XYZ position
				finalWeights # List of weights
			))
			
			# Next vert
			vertIter.next()
		
		# Get materials used by this mesh
		meshMaterials = GetMaterialsFromMesh(mesh, dagPath)
		
		# Loop through all faces
		polyIter = OpenMaya.MItMeshPolygon(dagPath)
		currentObjectVertexOffset = 0
		while not polyIter.isDone():
			fixedColor = False
			
			# Get this poly's material
			polyMaterial = meshMaterials[polyIter.index()]
			
			# Every face must have a material
			if polyMaterial == None:
				PrintWarning("Found no material on face '%s.f[%d]'; ignoring face" % (dagPath.partialPathName(), polyIter.index()))
				polyIter.next()
				continue
			
			# Add this poly's material to the global list of used materials
			if not polyMaterial[0] in materialDict:
				materialDict[polyMaterial[0]] = len(materials)
				materials.append(polyMaterial)
			
			# Get vertex indices of this poly, and the vertex indices of this poly's triangles
			trianglePoints = OpenMaya.MPointArray()
			triangleIndices = OpenMaya.MIntArray()
			vertexIndices = OpenMaya.MIntArray()
			polyIter.getTriangles(trianglePoints, triangleIndices)
			polyIter.getVertices(vertexIndices)
			
			# localTriangleIndices is the same as triangleIndices, except each vertex is listed as the face-relative index intead of the object-realtive index
			localTriangleIndices = VerticesObjRelToLocalRel(vertexIndices, triangleIndices)
			if localTriangleIndices == False:
				return "Failed to convert object-relative vertices to face-relative on poly '%s.f[%d]'" % (dagPath.partialPathName(), polyIter.index())
			
			# Note: UVs, normals, and colors, are "per-vertex per face", because even though two faces may share
			# a vertex, they might have different UVs, colors, or normals. So, each face has to contain this info
			# for each of it's vertices instead of each vertex alone
			Us = OpenMaya.MFloatArray()
			Vs = OpenMaya.MFloatArray()
			normals = OpenMaya.MVectorArray()
			polyIter.getUVs(Us, Vs)
			polyIter.getNormals(normals, OpenMaya.MSpace.kWorld)
			
			# Add each triangle in this poly to the global face list
			for i in range(triangleIndices.length() // 3): # vertexIndices.length() has 3 values per triangle
				# Put local indices into an array for easy access
				locals = [localTriangleIndices[i*3], localTriangleIndices[i*3+1], localTriangleIndices[i*3+2]]
				
				# Using polyIter.getColors() doesn't always work - sometimes values in the return array would
				# be valid Python objects, but when used they would cause Maya to completely crash. No idea
				# why that happens, but getting the colors individually fixed the problem.
				vert0Color = OpenMaya.MColor()
				vert1Color = OpenMaya.MColor()
				vert2Color = OpenMaya.MColor()
				polyIter.getColor(vert0Color, locals[0])
				polyIter.getColor(vert1Color, locals[1])
				polyIter.getColor(vert2Color, locals[2])
				
				# Make sure it has color
				if vert0Color == OpenMaya.MColor(0,0,0) or vert1Color == OpenMaya.MColor(0,0,0) or vert2Color == OpenMaya.MColor(0,0,0):
					if not fixedColor:
						PrintWarning("A color on face '%s.f[%d]' is 0" % (dagPath.partialPathName(), polyIter.index()))
					
				# Note: Vertices are in 0,2,1 order to make CoD happy
				tris.append((
					len(meshes)-1, # Shape index
					materialDict[polyMaterial[0]], # Matertial index 
					(currentStartingVertIndex + triangleIndices[i*3], currentStartingVertIndex + triangleIndices[i*3+2], currentStartingVertIndex + triangleIndices[i*3+1]), # Vert indices
					((Us[locals[0]], 1-Vs[locals[0]]),		(Us[locals[2]], 1-Vs[locals[2]]),		(Us[locals[1]], 1-Vs[locals[1]])),	  # UVs
					(vert0Color, 							vert2Color,								vert1Color),  		  				  # Colors
					(OpenMaya.MVector(normals[locals[0]]),	OpenMaya.MVector(normals[locals[2]]),	OpenMaya.MVector(normals[locals[1]])) # Normals; Must copy the normals into a new container, because the original is destructed at the end of this poltIter iteration.
				))
			
			# Next poly
			polyIter.next()
		
		# Update starting vertex index
		currentStartingVertIndex = len(verts)
		
		ProgressBarStep()
		
	# Error messages
	if len(meshes) == 0:
		return "No meshes selected to export."
	if len(verts) == 0:
		return "No vertices found in selected meshes."
	if len(tris) == 0:
		return "No faces found in selected meshes."
	if len(materials) == 0:
		return "No materials found on the selected meshes."
		
	# Done!
	return {"meshes": meshes, "verts": verts, "faces": tris, "materials": materials}

	
	
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------
# ----------------------------------------------------------------------------- XANIMS -----------------------------------------------------------------------------
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------
def CreateXAnimWindow():
	# Create window
	if cmds.control(OBJECT_NAMES['xanim'][0], exists=True):
		cmds.deleteUI(OBJECT_NAMES['xanim'][0])
	
	cmds.window(OBJECT_NAMES['xanim'][0], title=OBJECT_NAMES['xanim'][1], width=1, height=1, retain=True, maximizeButton=False)
	form = cmds.formLayout(OBJECT_NAMES['xanim'][0]+"_Form")
	
	# Controls
	slotDropDown = cmds.optionMenu(OBJECT_NAMES['xanim'][0]+"_SlotDropDown", changeCommand="CoDExportTools.RefreshXAnimWindow()", annotation="Each slot contains different a export path, frame range, notetrack, and saved selection")
	for i in range(1, EXPORT_WINDOW_NUMSLOTS+1):
		cmds.menuItem(OBJECT_NAMES['xmodel'][0]+"_SlotDropDown"+("_s%i" % i), label="Slot %i" % i)
	
	separator1 = cmds.separator(style='in')
	separator2 = cmds.separator(style='in')
	separator3 = cmds.separator(style='in')
	
	framesLabel = cmds.text(label="Frames:", annotation="Range of frames to export")
	framesStartField = cmds.intField(OBJECT_NAMES['xanim'][0]+"_FrameStartField", height=21, width=35, minValue=0, changeCommand=XAnimWindow_UpdateFrameRange, annotation="Starting frame to export (inclusive)")
	framesToLabel = cmds.text(label="to")
	framesEndField = cmds.intField(OBJECT_NAMES['xanim'][0]+"_FrameEndField", height=21, width=35, minValue=0, changeCommand=XAnimWindow_UpdateFrameRange, annotation="Ending frame to export (inclusive)")
	fpsLabel = cmds.text(label="FPS:")
	fpsField = cmds.intField(OBJECT_NAMES['xanim'][0]+"_FPSField", height=21, width=35, value=1, minValue=1, changeCommand=XAnimWindow_UpdateFramerate, annotation="Animation FPS")
	
	notetracksLabel = cmds.text(label="Notetrack:", annotation="Notetrack info for the animation")
	noteList = cmds.textScrollList(OBJECT_NAMES['xanim'][0]+"_NoteList", allowMultiSelection=False, selectCommand=XAnimWindow_SelectNote, annotation="List of notes in the notetrack")
	addNoteButton = cmds.button(label="Add Note", width=75, command=XAnimWindow_AddNote, annotation="Add a note to the notetrack")
	removeNoteButton = cmds.button(label="Remove Note", command=XAnimWindow_RemoveNote, annotation="Remove the currently selected note from the notetrack")
	noteFrameLabel = cmds.text(label="Frame:", annotation="The frame the currently selected note is applied to")
	noteFrameField = cmds.intField(OBJECT_NAMES['xanim'][0]+"_NoteFrameField", changeCommand=XAnimWindow_UpdateNoteFrame, height=21, width=30, minValue=0, annotation="The frame the currently selected note is applied to")
	
	saveToLabel = cmds.text(label="Save to:", annotation="This is where .xanim_export is saved to")
	saveToField = cmds.textField(OBJECT_NAMES['xanim'][0]+"_SaveToField", height=21, changeCommand="CoDExportTools.GeneralWindow_SaveToField('xanim')", annotation="This is where .xanim_export is saved to")
	fileBrowserButton = cmds.button(label="...", height=21, command="CoDExportTools.GeneralWindow_FileBrowser('xanim', \"XAnim Intermediate File (*.xanim_export)\")", annotation="Open a file browser dialog")
	
	exportSelectedButton = cmds.button(label="Export Selected", command="CoDExportTools.GeneralWindow_ExportSelected('xanim', False)", annotation="Export all currently selected joints from the scene (specified frames)\nWarning: Will automatically overwrite if the export path if it already exists")
	saveSelectionButton = cmds.button(label="Save Selection", command="CoDExportTools.GeneralWindow_SaveSelection('xanim')", annotation="Save the current object selection")
	getSavedSelectionButton = cmds.button(label="Get Saved Selection", command="CoDExportTools.GeneralWindow_GetSavedSelection('xanim')", annotation="Reselect the saved selection")
	
	exportMultipleSlotsButton = cmds.button(label="Export Multiple Slots", command="CoDExportTools.GeneralWindow_ExportMultiple('xanim')", annotation="Automatically export multiple slots at once, using each slot's saved selection")
	exportInMultiExportCheckbox = cmds.checkBox(OBJECT_NAMES['xanim'][0]+"_UseInMultiExportCheckBox", label="Use current slot for Export Multiple", changeCommand="CoDExportTools.GeneralWindow_ExportInMultiExport('xanim')", annotation="Check this make the 'Export Multiple Slots' button export this slot")
	
	# Setup form
	cmds.formLayout(form, edit=True,
		attachForm=[(slotDropDown, 'top', 6), (slotDropDown, 'left', 10), (slotDropDown, 'right', 10),
					(separator1, 'left', 0), (separator1, 'right', 0),
					(framesLabel, 'left', 10),
					(fpsLabel, 'left', 10),
					(notetracksLabel, 'left', 10),
					(noteList, 'left', 10),
					(addNoteButton, 'right', 10),
					(removeNoteButton, 'right', 10),
					(noteFrameField, 'right', 10),
					(separator2, 'left', 0), (separator2, 'right', 0),
					(saveToLabel, 'left', 12),
					(fileBrowserButton, 'right', 10),
					(exportMultipleSlotsButton, 'bottom', 6), (exportMultipleSlotsButton, 'left', 10),
					(exportInMultiExportCheckbox, 'bottom', 9), (exportInMultiExportCheckbox, 'right', 6),
					(exportSelectedButton, 'left', 10),
					(saveSelectionButton, 'right', 10),
					(separator3, 'left', 0), (separator3, 'right', 0)],
		
		attachControl=[	(separator1, 'top', 6, slotDropDown),
						(framesLabel, 'top', 8, separator1),
						(framesStartField, 'top', 5, separator1), (framesStartField, 'left', 4, framesLabel),
						(framesToLabel, 'top', 8, separator1), (framesToLabel, 'left', 4+35+4, framesLabel),
						(framesEndField, 'top', 5, separator1), (framesEndField, 'left', 4, framesToLabel),
						(fpsLabel, 'top', 8, framesStartField),
						(fpsField, 'top', 5, framesStartField), (fpsField, 'left', 21, fpsLabel),
						(notetracksLabel, 'top', 5, fpsField),
						(noteList, 'top', 5, notetracksLabel), (noteList, 'right', 10, removeNoteButton), (noteList, 'bottom', 7, separator2),
						(addNoteButton, 'top', 5, notetracksLabel),
						(removeNoteButton, 'top', 5, addNoteButton),
						(noteFrameField, 'top', 5, removeNoteButton),
						(noteFrameLabel, 'top', 8, removeNoteButton), (noteFrameLabel, 'right', 4, noteFrameField),
						(separator2, 'bottom', 5, fileBrowserButton),
						(saveToLabel, 'bottom', 10, exportSelectedButton),
						(saveToField, 'bottom', 5, exportSelectedButton), (saveToField, 'left', 5, saveToLabel), (saveToField, 'right', 5, fileBrowserButton),
						(fileBrowserButton, 'bottom', 5, exportSelectedButton),
						(exportSelectedButton, 'bottom', 5, separator3),
						(saveSelectionButton, 'bottom', 5, separator3),
						(getSavedSelectionButton, 'bottom', 5, separator3), (getSavedSelectionButton, 'right', 10, saveSelectionButton),
						(separator3, 'bottom', 5, exportMultipleSlotsButton)
						])

def XAnimWindow_UpdateFrameRange(required_parameter):
	slotIndex = cmds.optionMenu(OBJECT_NAMES['xanim'][0]+"_SlotDropDown", query=True, select=True)
	start = cmds.intField(OBJECT_NAMES['xanim'][0]+"_FrameStartField", query=True, value=True)
	end = cmds.intField(OBJECT_NAMES['xanim'][0]+"_FrameEndField", query=True, value=True)
	cmds.setAttr(OBJECT_NAMES['xanim'][2]+(".frameRanges[%i]" % slotIndex), start, end, type='long2')

def XAnimWindow_UpdateFramerate(required_parameter):
	slotIndex = cmds.optionMenu(OBJECT_NAMES['xanim'][0]+"_SlotDropDown", query=True, select=True)
	fps = cmds.intField(OBJECT_NAMES['xanim'][0]+"_FPSField", query=True, value=True)
	cmds.setAttr(OBJECT_NAMES['xanim'][2]+(".framerate[%i]" % slotIndex), fps)

def XAnimWindow_AddNote(required_parameter):
	slotIndex = cmds.optionMenu(OBJECT_NAMES['xanim'][0]+"_SlotDropDown", query=True, select=True)
	if cmds.promptDialog(title="Add Note to Slot %i's Notetrack" % slotIndex, message="Enter the note's name:\t\t  ") != "Confirm":
		return
	
	userInput = cmds.promptDialog(query=True, text=True)
	noteName = "".join([c for c in userInput if c.isalnum() or c=="_"]) # Remove all non-alphanumeric characters
	if noteName == "":
		MessageBox("Invalid note name")
		return
		
	existingItems = cmds.textScrollList(OBJECT_NAMES['xanim'][0]+"_NoteList", query=True, allItems=True)
	
	if existingItems != None and noteName in existingItems:
		MessageBox("A note with this name already exists")
		
	noteList = cmds.getAttr(OBJECT_NAMES['xanim'][2]+(".notetracks[%i]" % slotIndex)) or ""
	noteList += "%s:%i," % (noteName, cmds.currentTime(query=True))
	cmds.setAttr(OBJECT_NAMES['xanim'][2]+(".notetracks[%i]" % slotIndex), noteList, type='string')
	
	cmds.textScrollList(OBJECT_NAMES['xanim'][0]+"_NoteList", edit=True, append=noteName, selectIndexedItem=len((existingItems or []))+1)
	XAnimWindow_SelectNote()
	
def XAnimWindow_RemoveNote(required_parameter):
	slotIndex = cmds.optionMenu(OBJECT_NAMES['xanim'][0]+"_SlotDropDown", query=True, select=True)
	currentIndex = cmds.textScrollList(OBJECT_NAMES['xanim'][0]+"_NoteList", query=True, selectIndexedItem=True)
	if currentIndex != None and len(currentIndex) > 0 and currentIndex[0] >= 1:
		currentIndex = currentIndex[0]
		cmds.textScrollList(OBJECT_NAMES['xanim'][0]+"_NoteList", edit=True, removeIndexedItem=currentIndex)
		noteList = cmds.getAttr(OBJECT_NAMES['xanim'][2]+(".notetracks[%i]" % slotIndex)) or ""
		notes = noteList.split(",")
		del notes[currentIndex-1]
		noteList = ",".join(notes)
		cmds.setAttr(OBJECT_NAMES['xanim'][2]+(".notetracks[%i]" % slotIndex), noteList, type='string')
		XAnimWindow_SelectNote()
		
def XAnimWindow_UpdateNoteFrame(newFrame):
	slotIndex = cmds.optionMenu(OBJECT_NAMES['xanim'][0]+"_SlotDropDown", query=True, select=True)
	currentIndex = cmds.textScrollList(OBJECT_NAMES['xanim'][0]+"_NoteList", query=True, selectIndexedItem=True)
	if currentIndex != None and len(currentIndex) > 0 and currentIndex[0] >= 1:
		currentIndex = currentIndex[0]
		noteList = cmds.getAttr(OBJECT_NAMES['xanim'][2]+(".notetracks[%i]" % slotIndex)) or ""
		notes = noteList.split(",")
		parts = notes[currentIndex-1].split(":")
		if len(parts) < 2:
			cmds.error("Error parsing notetrack string (A) at %i: %s" % (currentIndex, noteList))
		notes[currentIndex-1] = "%s:%i" % (parts[0], newFrame)
		noteList = ",".join(notes)
		cmds.setAttr(OBJECT_NAMES['xanim'][2]+(".notetracks[%i]" % slotIndex), noteList, type='string')
		
def XAnimWindow_SelectNote():
	slotIndex = cmds.optionMenu(OBJECT_NAMES['xanim'][0]+"_SlotDropDown", query=True, select=True)
	currentIndex = cmds.textScrollList(OBJECT_NAMES['xanim'][0]+"_NoteList", query=True, selectIndexedItem=True)
	if currentIndex != None and len(currentIndex) > 0 and currentIndex[0] >= 1:
		currentIndex = currentIndex[0]
		noteList = cmds.getAttr(OBJECT_NAMES['xanim'][2]+(".notetracks[%i]" % slotIndex)) or ""
		notes = noteList.split(",")
		parts = notes[currentIndex-1].split(":")
		if len(parts) < 2:
			cmds.error("Error parsing notetrack string (B) at %i: %s" % (currentIndex, noteList))
			
		frame=0
		try: 
			frame = int(parts[1])
		except ValueError:
			pass
			
		noteFrameField = cmds.intField(OBJECT_NAMES['xanim'][0]+"_NoteFrameField", edit=True, value=frame)
		
def RefreshXAnimWindow():
	# Refresh/create node
	if len(cmds.ls(OBJECT_NAMES['xanim'][2])) == 0:
		cmds.createNode("renderLayer", name=OBJECT_NAMES['xanim'][2], skipSelect=True)
	
	cmds.lockNode(OBJECT_NAMES['xanim'][2], lock=False)
	
	if not cmds.attributeQuery("slot", node=OBJECT_NAMES['xanim'][2], exists=True):
		cmds.addAttr(OBJECT_NAMES['xanim'][2], longName="slot", attributeType='short', defaultValue=1)
	if not cmds.attributeQuery("paths", node=OBJECT_NAMES['xanim'][2], exists=True):
		cmds.addAttr(OBJECT_NAMES['xanim'][2], longName="paths", multi=True, dataType='string')
		cmds.setAttr(OBJECT_NAMES['xanim'][2]+".paths", size=EXPORT_WINDOW_NUMSLOTS)
	if not cmds.attributeQuery("selections", node=OBJECT_NAMES['xanim'][2], exists=True):
		cmds.addAttr(OBJECT_NAMES['xanim'][2], longName="selections", multi=True, dataType='stringArray')
		cmds.setAttr(OBJECT_NAMES['xanim'][2]+".selections", size=EXPORT_WINDOW_NUMSLOTS)
	if not cmds.attributeQuery("frameRanges", node=OBJECT_NAMES['xanim'][2], exists=True):
		cmds.addAttr(OBJECT_NAMES['xanim'][2], longName="frameRanges", multi=True, dataType='long2')
		cmds.setAttr(OBJECT_NAMES['xanim'][2]+".frameRanges", size=EXPORT_WINDOW_NUMSLOTS)
	if not cmds.attributeQuery("framerate", node=OBJECT_NAMES['xanim'][2], exists=True):
		cmds.addAttr(OBJECT_NAMES['xanim'][2], longName="framerate", multi=True, attributeType='long', defaultValue=30)
		cmds.setAttr(OBJECT_NAMES['xanim'][2]+".framerate", size=EXPORT_WINDOW_NUMSLOTS)
	if not cmds.attributeQuery("notetracks", node=OBJECT_NAMES['xanim'][2], exists=True):
		cmds.addAttr(OBJECT_NAMES['xanim'][2], longName="notetracks", multi=True, dataType='string') # Formatted as "<name>:<frame>,<name>:<frame>,..."
		cmds.setAttr(OBJECT_NAMES['xanim'][2]+".notetracks", size=EXPORT_WINDOW_NUMSLOTS)
	if not cmds.attributeQuery("useinmultiexport", node=OBJECT_NAMES['xanim'][2], exists=True):
		cmds.addAttr(OBJECT_NAMES['xanim'][2], longName="useinmultiexport", multi=True, attributeType='bool', defaultValue=False)
		cmds.setAttr(OBJECT_NAMES['xanim'][2]+".useinmultiexport", size=EXPORT_WINDOW_NUMSLOTS)
	
	cmds.lockNode(OBJECT_NAMES['xanim'][2], lock=True)
	
	# Set values
	slotIndex = cmds.optionMenu(OBJECT_NAMES['xanim'][0]+"_SlotDropDown", query=True, select=True)	
	cmds.setAttr(OBJECT_NAMES['xanim'][2]+".slot", slotIndex)
	
	path = cmds.getAttr(OBJECT_NAMES['xanim'][2]+(".paths[%i]" % slotIndex))
	cmds.textField(OBJECT_NAMES['xanim'][0]+"_SaveToField", edit=True, fileName=path)
	
	frameRange = cmds.getAttr(OBJECT_NAMES['xanim'][2]+(".frameRanges[%i]" % slotIndex))
	if frameRange == None:
		cmds.setAttr(OBJECT_NAMES['xanim'][2]+(".frameRanges[%i]" % slotIndex), 0, 0, type='long2')
		cmds.intField(OBJECT_NAMES['xanim'][0]+"_FrameStartField", edit=True, value=0)
		cmds.intField(OBJECT_NAMES['xanim'][0]+"_FrameEndField", edit=True, value=0)
	else:
		cmds.intField(OBJECT_NAMES['xanim'][0]+"_FrameStartField", edit=True, value=frameRange[0][0])
		cmds.intField(OBJECT_NAMES['xanim'][0]+"_FrameEndField", edit=True, value=frameRange[0][1])
	
	framerate = cmds.getAttr(OBJECT_NAMES['xanim'][2]+(".framerate[%i]" % slotIndex))
	cmds.intField(OBJECT_NAMES['xanim'][0]+"_FPSField", edit=True, value=framerate)
	
	noteFrameField = cmds.intField(OBJECT_NAMES['xanim'][0]+"_NoteFrameField", edit=True, value=0)
	cmds.textScrollList(OBJECT_NAMES['xanim'][0]+"_NoteList", edit=True, removeAll=True)
	noteList = cmds.getAttr(OBJECT_NAMES['xanim'][2]+(".notetracks[%i]" % slotIndex)) or ""
	notes = noteList.split(",")
	for note in notes:
		parts = note.split(":")
		if note.strip() == "" or len(parts) == 0:
			continue
		
		name = "".join([c for c in parts[0] if c.isalnum() or c=="_"])
		if name == "":
			continue
		
		cmds.textScrollList(OBJECT_NAMES['xanim'][0]+"_NoteList", edit=True, append=name)
		
	useInMultiExport = cmds.getAttr(OBJECT_NAMES['xanim'][2]+(".useinmultiexport[%i]" % slotIndex))
	cmds.checkBox(OBJECT_NAMES['xanim'][0]+"_UseInMultiExportCheckBox", edit=True, value=useInMultiExport)
	
def ExportXAnim(filePath):
	# Progress bar
	numSelectedObjects = len(cmds.ls(selection=True))
	if numSelectedObjects == 0:
		return "Error: No objects selected for export"
	
	cmds.progressBar(OBJECT_NAMES['progress'][0], edit=True, maxValue=numSelectedObjects+1)
	
	# Get data
	joints = GetJointList()
	if len(joints) == 0:
		return "Error: No joints selected for export"
	if len(joints) > 128:
		return "Error: More than 128 joints"
	
	# Get settings
	frameStart = cmds.intField(OBJECT_NAMES['xanim'][0]+"_FrameStartField", query=True, value=True)
	frameEnd = cmds.intField(OBJECT_NAMES['xanim'][0]+"_FrameEndField", query=True, value=True)
	fps = cmds.intField(OBJECT_NAMES['xanim'][0]+"_FPSField", query=True, value=True)
	if frameStart < 0 or frameStart > frameEnd:
		return "Error: Invalid frame range (start < 0 or start > end)"
	if fps <= 0:
		return "Error: Invalid FPS (fps < 0)"
	
	# Open file
	f = None
	try:
		# Create export directory if it doesn't exist
		directory = os.path.dirname(filePath)
		if not os.path.exists(directory):
			os.makedirs(directory)
		
		# Create files
		f = open(filePath, 'w')
	except (IOError, OSError) as e:
		typex, value, traceback = sys.exc_info()
		return "Unable to create files:\n\n%s" % value.strerror
	
	# Write header
	f.write("// Export filename: '%s'\n" % os.path.normpath(filePath))
	if cmds.file(query=True, exists=True):
		f.write("// Source filename: '%s'\n" % os.path.normpath(os.path.abspath(cmds.file(query=True, sceneName=True))))
	else:
		f.write("// Source filename: Unsaved\n")
	f.write("// Export time: %s\n\n" % datetime.datetime.now().strftime("%a %b %d %Y, %H:%M:%S"))
	f.write("ANIMATION\n")
	f.write("VERSION 3\n\n")
	
	# Write parts
	f.write("NUMPARTS %i\n" % len(joints))
	for i, joint in enumerate(joints):
		name = joint[1].partialPathName().split("|")
		name = name[len(name)-1].split(":") # Remove namespace prefixes
		name = name[len(name)-1]
		f.write("PART %i \"%s\"\n" % (i, name))
	
	# Write animation data
	f.write("\nFRAMERATE %i\n" % fps)
	f.write("NUMFRAMES %i\n" % (frameEnd-frameStart+1))
	
	currentFrame = cmds.currentTime(query=True)
	for i in range(frameStart, frameEnd+1):
		f.write("\nFRAME %i" % i)
		cmds.currentTime(i)
		
		for j, joint in enumerate(joints):
			f.write("\nPART %i\n" % j)
			WriteJointData(f, joint[1])
	
	cmds.currentTime(currentFrame)
	
	# Write notetrack
	slotIndex = cmds.optionMenu(OBJECT_NAMES['xanim'][0]+"_SlotDropDown", query=True, select=True)
	noteList = cmds.getAttr(OBJECT_NAMES['xanim'][2]+(".notetracks[%i]" % slotIndex)) or ""
	notes = noteList.split(",")
	cleanNotes = []
	
	for note in notes:
		parts = note.split(":")
		if note.strip() == "" or len(parts) < 2:
			continue
			
		name = "".join([c for c in parts[0] if c.isalnum() or c=="_"])
		if name == "":
			continue
			
		frame=0
		try: 
			frame = int(parts[1])
		except ValueError:
			continue
			
		cleanNotes.append((name, frame))
		
	f.write("\nNOTETRACKS\n")
	for i, joint in enumerate(joints):
		if i == 0 and len(cleanNotes) > 0:
			f.write("\nPART 0\nNUMTRACKS 1\nNOTETRACK 0\n")
			f.write("NUMKEYS %i\n" % len(cleanNotes))
			for note in cleanNotes:
				f.write("FRAME %i \"%s\"\n" % (note[1], note[0]))
		else:
			f.write("\nPART %i\nNUMTRACKS 0\n" % i)
	
	f.close()
	ProgressBarStep()
	cmds.refresh()

	
	
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------
# ------------------------------------------------------------------------ VIEWMODEL TOOLS -------------------------------------------------------------------------
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------
def DoesObjectExist(name, type):
	if not cmds.objExists(name):
		MessageBox("Error: Missing %s '%s'" % (type, name))
		return False
		
	return True

def CreateNewGunsleeveMayaFile(required_parameter):
	global WarningsDuringExport
	
	# Save reminder
	if not SaveReminder(False):
		return
	
	# Get paths
	filePath = cmds.file(query=True, sceneName=True)
	split1 = os.path.split(filePath)
	split2 = os.path.splitext(split1[1])
	exportPath = os.path.join(split1[0], "gunsleeves_" + split2[0] + ".xmodel_export")
	
	# Create a new file and import models
	cmds.file(force=True, newFile=True)
	cmds.file(os.path.join(GetRootFolder(), "bin/maya/rigs/viewmodel/ViewModel_DefMesh.mb"), i=True, type="mayaBinary")
	cmds.file(filePath, i=True, type="mayaBinary")
	
	# Check to make sure objects exist
	if not DoesObjectExist("J_Gun", "joint"): return
	if not DoesObjectExist("tag_weapon", "tag"): return
	if not DoesObjectExist("GunExport", "object set"): return
	if not DoesObjectExist("DefViewSkeleton", "object set"): return
	if not DoesObjectExist("tag_view", "tag"): return
	if not cmds.objExists("viewmodelSleeves_OpForce") and not cmds.objExists("viewmodelSleeves_Marines"):
		MessageBox("Error: Missing viewsleeves 'viewmodelSleeves_OpForce' or 'viewmodelSleeves_Marines'")
		return
		
	# Attach gun to rig
	cmds.select("J_Gun", replace=True)
	cmds.select("tag_weapon", add=True)
	cmds.parent()
	
	# Select things to export
	cmds.select("GunExport", replace=True)
	cmds.select("DefViewSkeleton", toggle=True)
	cmds.select("tag_view", toggle=True)
	if cmds.objExists("viewmodelSleeves_OpForce"):
		cmds.select("viewmodelSleeves_OpForce", toggle=True, hierarchy=True)
	else:
		cmds.select("viewmodelSleeves_Marines", toggle=True, hierarchy=True)
	
	# Export
	if cmds.control("w"+OBJECT_NAMES['progress'][0], exists=True):
		cmds.deleteUI("w"+OBJECT_NAMES['progress'][0])
	progressWindow = cmds.window("w"+OBJECT_NAMES['progress'][0], title=OBJECT_NAMES['progress'][1], width=302, height=22)
	cmds.columnLayout()
	progressControl = cmds.progressBar(OBJECT_NAMES['progress'][0], width=300)
	cmds.showWindow(progressWindow)
	cmds.refresh() # Force the progress bar to be drawn
	
	# Export
	WarningsDuringExport = 0
	response = None
	try:
		response = ExportXModel(exportPath)
	except Exception as e:
		response = "An unhandled error occurred during export:\n\n" + traceback.format_exc()
	
	# Delete progress bar
	cmds.deleteUI(progressWindow, window=True)
	
	# Handle response
	if isinstance(response, str):
		MessageBox(response)
	elif WarningsDuringExport > 0:
		MessageBox("Warnings occurred during export. Check the script editor output for more details.")
	
	if not isinstance(response, str):
		MessageBox("Export saved to\n\n" + os.path.normpath(exportPath))
	
def CreateNewViewmodelRigFile(required_parameter):
	# Save reminder
	if not SaveReminder(False):
		return
	
	# Get path
	filePath = cmds.file(query=True, sceneName=True)
	
	# Create a new file and import models
	cmds.file(force=True, newFile=True)
	cmds.file(os.path.join(GetRootFolder(), "bin/maya/rigs/viewmodel/ViewModel_Rig.mb"), reference=True, type="mayaBinary", namespace="rig", options="v=0")
	cmds.file(filePath, reference=True, type="mayaBinary", namespace="VM_Gun")
	
	# Check to make sure objects exist
	if not DoesObjectExist("VM_Gun:J_Gun", "joint"): return
	if not cmds.objExists("rig:DefMesh:tag_weapon") and not cmds.objExists("ConRig:DefMesh:tag_weapon"):
		MessageBox("Error: Missing viewsleeves 'rig:DefMesh:tag_weapon' or 'ConRig:DefMesh:tag_weapon'")
		return
	
	# Connect gun to rig
	if cmds.objExists("rig:DefMesh:tag_weapon"):
		cmds.select("rig:DefMesh:tag_weapon", replace=True)
	else:
		cmds.select("ConRig:DefMesh:tag_weapon", replace=True)
		
	cmds.select("VM_Gun:J_Gun", toggle=True)
	cmds.parentConstraint(weight=1, name="VMParentConstraint")
	cmds.select(clear=True)
	
def SwitchGunInCurrentRigFile(required_parameter):
	# Save reminder
	if not SaveReminder():
		return
	
	# Make sure the rig is correct
	if not cmds.objExists("rig:DefMesh:tag_weapon") and not cmds.objExists("ConRig:DefMesh:tag_weapon"):
		MessageBox("Error: Missing rig:DefMesh:tag_weapon' or 'ConRig:DefMesh:tag_weapon'")
		return
	
	if not DoesObjectExist("VM_Gun:J_Gun", "joint"): return
	
	# Prompt user to select a new gun file
	gunPath = cmds.fileDialog2(fileMode=1, fileFilter="Maya Files (*.ma *.mb)", caption="Select a New Gun File", startingDirectory=GetRootFolder())
	if gunPath == None or len(gunPath) == 0 or gunPath[0].strip() == "":
		return
	gunPath = gunPath[0].strip()
	
	# Delete the constraint
	cmds.delete("VMParentConstraint")
	
	# Delete any hand attachments
	if cmds.objExists("rig:Hand_Extra_RI_GRP.Parent"):
		parentRI = cmds.getAttr("rig:Hand_Extra_RI_GRP.Parent")
		if parentRI != "":
			cmds.delete(parentRI)
	if cmds.objExists("rig:Hand_Extra_LE_GRP.Parent"):
		parentLE = cmds.getAttr("rig:Hand_Extra_LE_GRP.Parent")
		if parentLE != "":
			cmds.delete(parentLE)
		
	# Switch guns
	cmds.file(gunPath, loadReference="VM_GunRN");
	
	# Connect gun to rig
	if cmds.objExists("rig:DefMesh:tag_weapon"):
		cmds.select("rig:DefMesh:tag_weapon", replace=True)
	else:
		cmds.select("ConRig:DefMesh:tag_weapon", replace=True)
		
	cmds.select("VM_Gun:J_Gun", toggle=True)
	cmds.parentConstraint(weight=1, name="VMParentConstraint")
	cmds.select(clear=True)
	
	
	
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------
# ---------------------------------------------------------------------------- GENERAL -----------------------------------------------------------------------------
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------
def SaveReminder(allowUnsaved=True):
	if cmds.file(query=True, modified=True):
		if cmds.file(query=True, exists=True):
			result = cmds.confirmDialog(message="Save changes to %s?" % cmds.file(query=True, sceneName=True), button=["Yes", "No", "Cancel"], defaultButton="Yes", title="Save Changes")
			if result == "Yes":
				cmds.file(save=True)
			elif result != "No":
				return False
		else: # The file has never been saved (has no name)
			if allowUnsaved:
				result = cmds.confirmDialog(message="The current scene is not saved. Continue?", button=["Yes", "No"], defaultButton="Yes", title="Save Changes")
				if result != "Yes":
					return False
			else:
				MessageBox("The scene needs to be saved first")
				return False
				
	return True

def PrintWarning(message):
	global WarningsDuringExport
	if WarningsDuringExport < MAX_WARNINGS_SHOWN:
		print("WARNING: %s" % message)
		WarningsDuringExport += 1
	elif WarningsDuringExport == MAX_WARNINGS_SHOWN:
		print("More warnings not shown because printing text is slow...\n")
		WarningsDuringExport = MAX_WARNINGS_SHOWN+1

def MessageBox(message):
	cmds.confirmDialog(message=message, button='OK', defaultButton='OK', title=OBJECT_NAMES['menu'][1])
	
def CheckForUpdates():
	mostRecentVersion = FILE_VERSION
	#versionInfo = ""
	
	try:
		response = urllib_request.urlopen("http://www.aidanshafran.com/auto-updater-info/cod-maya-export-tools-version.html", timeout=2).read().decode("utf-8", errors="replace").splitlines()
		if len(response) > 0:
			mostRecentVersion = float(response[0])
		#if len(response) > 1 and response[1].startswith("INFO "):
		#	versionInfo = response[1][5:]
	except (ValueError, urllib_error.URLError, urllib_error.HTTPError, socket.timeout):
		return None
	
	if mostRecentVersion > FILE_VERSION:
		return mostRecentVersion
	else:
		return None

def GoToExporterForumTopic():
	webbrowser.open("http://ugx-mods.com/forum/index.php?topic=1295.0")
		
def ShowWindow(windowID):
	globals()[OBJECT_NAMES[windowID][3]]() # Refresh window
	cmds.showWindow(OBJECT_NAMES[windowID][0])

def ProgressBarStep():
	cmds.progressBar(OBJECT_NAMES['progress'][0], edit=True, step=1)
	
def SetRootFolder(required_parameter, msg=None):
	# Get current root folder (this also makes sure the reg key exists)
	codRootPath = GetRootFolder(False)
	
	# Open input box
	if cmds.promptDialog(title="Set CoD Root Path", message=msg or "Change your CoD root path:\t\t\t", text=codRootPath) != "Confirm":
		return None
	
	codRootPath = cmds.promptDialog(query=True, text=True)
	
	# Check to make sure the path exists
	if not os.path.isdir(codRootPath):
		MessageBox("Given root path does not exist")
		return None
		
	# Set path
	storageKey = reg.OpenKey(GLOBAL_STORAGE_REG_KEY[0], GLOBAL_STORAGE_REG_KEY[1], 0, reg.KEY_SET_VALUE)
	reg.SetValueEx(storageKey, "CoDRootPath", 0, reg.REG_SZ, codRootPath)
	reg.CloseKey(storageKey)
	
	return codRootPath
	
def GetRootFolder(firstTimePrompt=True):
	codRootPath = ""
	
	try:
		storageKey = reg.OpenKey(GLOBAL_STORAGE_REG_KEY[0], GLOBAL_STORAGE_REG_KEY[1])
		codRootPath = reg.QueryValueEx(storageKey, "CoDRootPath")[0]
		reg.CloseKey(storageKey)
	except OSError:
		# First time, create key
		storageKey = reg.CreateKey(GLOBAL_STORAGE_REG_KEY[0], GLOBAL_STORAGE_REG_KEY[1])
		
		# Try to get root path from cod registry value
		try:
			codKey = reg.OpenKey(reg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Wow6432Node\Activision\Call of Duty WAW")
			codRootPath = reg.QueryValueEx(codKey, "InstallPath")[0]
			reg.CloseKey(codKey)
		except OSError:
			pass
		
		if not os.path.isdir(codRootPath):
			codRootPath = ""
		
		# Set root path value
		reg.SetValueEx(storageKey, "CoDRootPath", 0, reg.REG_SZ, codRootPath)

		# First-time prompt
		if firstTimePrompt:
			result = SetRootFolder(None, msg="Your CoD root folder path hasn't been confirmed yet. If the following is not\ncorrect, please fix it:")
			if result:
				codRootPath = result
		
	return codRootPath
	
# GeneralWindow_... are callback functions that are used by both export windows
def GeneralWindow_SaveToField(windowID):
	slotIndex = cmds.optionMenu(OBJECT_NAMES[windowID][0]+"_SlotDropDown", query=True, select=True)
	filePath = cmds.textField(OBJECT_NAMES[windowID][0]+"_SaveToField", query=True, fileName=True)
	cmds.setAttr(OBJECT_NAMES[windowID][2]+(".paths[%i]" % slotIndex), filePath, type='string')
	
def GeneralWindow_FileBrowser(windowID, formatExtension):
	saveTo = cmds.fileDialog2(fileMode=0, fileFilter=formatExtension, caption="Export To", startingDirectory=GetRootFolder())
	if saveTo == None or len(saveTo) == 0 or saveTo[0].strip() == "":
		return
	saveTo = saveTo[0].strip()
	
	cmds.textField(OBJECT_NAMES[windowID][0]+"_SaveToField", edit=True, fileName=saveTo)
	GeneralWindow_SaveToField(windowID)

def GeneralWindow_SaveSelection(windowID):
	slotIndex = cmds.optionMenu(OBJECT_NAMES[windowID][0]+"_SlotDropDown", query=True, select=True)
	selection = cmds.ls(selection=True)
	if selection == None or len(selection) == 0:
		return
	cmds.setAttr(OBJECT_NAMES[windowID][2]+(".selections[%i]" % slotIndex), len(selection), *selection, type='stringArray')
	
def GeneralWindow_GetSavedSelection(windowID):
	slotIndex = cmds.optionMenu(OBJECT_NAMES[windowID][0]+"_SlotDropDown", query=True, select=True)
	selection = cmds.getAttr(OBJECT_NAMES[windowID][2]+(".selections[%i]" % slotIndex))
	if selection == None or len(selection) == 0:
		MessageBox("No selection saved to slot %i" % slotIndex)
		return False
	cmds.select(selection)
	return True

def GeneralWindow_ExportSelected(windowID, exportingMultiple):
	global WarningsDuringExport
	
	slotIndex = cmds.optionMenu(OBJECT_NAMES[windowID][0]+"_SlotDropDown", query=True, select=True)
	
	# Get path
	filePath = cmds.textField(OBJECT_NAMES[windowID][0]+"_SaveToField", query=True, fileName=True)
	if filePath.strip() == "":
		if exportingMultiple:
			MessageBox("Invalid path on slot %i:\n\nPath is empty." % slotIndex)
		else:
			MessageBox("Invalid path:\n\nPath is empty.")
		return
		
	if os.path.isdir(filePath):
		if exportingMultiple:
			MessageBox("Invalid path on slot %i:\n\nPath points to an existing directory." % slotIndex)
		else:
			MessageBox("Invalid path:\n\nPath points to an existing directory.")
		return
		
	# Save reminder
	if not exportingMultiple and not SaveReminder():
		return
	
	# Progress bar
	if cmds.control("w"+OBJECT_NAMES['progress'][0], exists=True):
		cmds.deleteUI("w"+OBJECT_NAMES['progress'][0])
	progressWindow = cmds.window("w"+OBJECT_NAMES['progress'][0], title=OBJECT_NAMES['progress'][1], width=302, height=22)
	cmds.columnLayout()
	progressControl = cmds.progressBar(OBJECT_NAMES['progress'][0], width=300)
	cmds.showWindow(progressWindow)
	cmds.refresh() # Force the progress bar to be drawn
	
	# Export
	if not exportingMultiple:
		WarningsDuringExport = 0
	response = None
	try:
		response = globals()[OBJECT_NAMES[windowID][4]](filePath)
	except Exception as e:
		response = "An unhandled error occurred during export:\n\n" + traceback.format_exc()
	
	# Delete progress bar
	cmds.deleteUI(progressWindow, window=True)
	
	# Handle response
	
	if isinstance(response, str):
		if exportingMultiple:
			MessageBox("Slot %i\n\n%s" % (slotIndex, response))
		else:
			MessageBox(response)
	elif WarningsDuringExport > 0 and not exportingMultiple:
		MessageBox("Warnings occurred during export. Check the script editor output for more details.")

def GeneralWindow_ExportMultiple(windowID):
	originalSlotIndex = cmds.optionMenu(OBJECT_NAMES[windowID][0]+"_SlotDropDown", query=True, select=True)
	any = False
	for i in range(1, EXPORT_WINDOW_NUMSLOTS+1):
		useInMultiExport = cmds.getAttr(OBJECT_NAMES[windowID][2]+(".useinmultiexport[%i]" % i))
		if useInMultiExport:
			any = True
			break
	
	if not any:
		MessageBox("No slots set to export.")
		return
	
	if not SaveReminder():
		return
		
	WarningsDuringExport = 0
	originalSelection = cmds.ls(selection=True)
	
	for i in range(1, EXPORT_WINDOW_NUMSLOTS+1):
		useInMultiExport = cmds.getAttr(OBJECT_NAMES[windowID][2]+(".useinmultiexport[%i]" % i))
		if useInMultiExport:
			print("Exporting slot %i in multiexport" % i)
			cmds.optionMenu(OBJECT_NAMES[windowID][0]+"_SlotDropDown", edit=True, select=i)
			globals()[OBJECT_NAMES[windowID][3]]() # Refresh window
			if GeneralWindow_GetSavedSelection(windowID):
				GeneralWindow_ExportSelected(windowID, True)
	
	if originalSelection == None or len(originalSelection) == 0:
		cmds.select(clear=True)
	else:
		cmds.select(originalSelection)
	
	if WarningsDuringExport > 0:
		MessageBox("Warnings occurred during export. Check the script editor output for more details.")			
	
	# Reset slot
	cmds.optionMenu(OBJECT_NAMES[windowID][0]+"_SlotDropDown", edit=True, select=originalSlotIndex)
	globals()[OBJECT_NAMES[windowID][3]]() # Refresh window
	
def GeneralWindow_ExportInMultiExport(windowID):
	slotIndex = cmds.optionMenu(OBJECT_NAMES[windowID][0]+"_SlotDropDown", query=True, select=True)
	useInMultiExport = cmds.checkBox(OBJECT_NAMES[windowID][0]+"_UseInMultiExportCheckBox", query=True, value=True)
	cmds.setAttr(OBJECT_NAMES[windowID][2]+(".useinmultiexport[%i]" % slotIndex), useInMultiExport)
	
def CreateMenu():
	cmds.setParent(mel.eval("$temp1=$gMainWindow"))
	
	if cmds.control(OBJECT_NAMES['menu'][0], exists=True):
		cmds.deleteUI(OBJECT_NAMES['menu'][0], menu=True)
	
	menu = cmds.menu(OBJECT_NAMES['menu'][0], label=OBJECT_NAMES["menu"][1], tearOff=True)
	cmds.menuItem(label=OBJECT_NAMES['xmodel'][1]+"...", command="CoDExportTools.ShowWindow('xmodel')")
	cmds.menuItem(label=OBJECT_NAMES['xanim'][1]+"...", command="CoDExportTools.ShowWindow('xanim')")
	
	# Viewmodel controls submenu
	cmds.menuItem(label="ViewModel Tools", subMenu=True)
	cmds.menuItem(label="Create New Gunsleeve Maya File", command=CreateNewGunsleeveMayaFile)
	cmds.menuItem(label="Create New ViewModel Rig File", command=CreateNewViewmodelRigFile)
	cmds.menuItem(label="Switch Gun in Current Rig File", command=SwitchGunInCurrentRigFile)
	
	# Root folder
	cmds.setParent(menu, menu=True)
	cmds.menuItem(divider=True)
	cmds.menuItem(label="Set CoD Root Folder", command=SetRootFolder)
	
	# For easy script updating
	#cmds.menuItem(divider=True)
	#cmds.menuItem(label="Reload Script", command="reload(CoDExportTools)")
	
	# Updates
	version = CheckForUpdates()
	if version:
		cmds.setParent(menu, menu=True)
		cmds.menuItem(divider=True)
		cmds.menuItem(label="A newer version (v%s) of CoD 5 Exporter Tools is available! (Click to visit forum topic)" % ('%f' % version).rstrip('0').rstrip('.'), command="CoDExportTools.GoToExporterForumTopic()")
	
# ---- Init ----
CreateMenu()
CreateXAnimWindow()
CreateXModelWindow()